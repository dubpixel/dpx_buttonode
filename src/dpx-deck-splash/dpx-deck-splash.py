#!/usr/bin/env python3
"""
dpx-deck-splash — draws a boot-time status screen (IP + mDNS hostname) onto
an attached Elgato Stream Deck, before Buttons/Satellite/Companion claims
the device.

Installed: /usr/local/bin/dpx-deck-splash.py
Service:   dpx-deck-splash.service (After=dpx-set-hostname.service,
           Before=/Conflicts=bitfocus-buttons-usb-relay.service,
           satellite.service, companion.service — see the unit file for
           the full hand-off story)

Phase 2/3, redesigned as a stage-then-execute config screen (v2 — the
first cut had MODE/NET independently long-press-committing, which was
confusing and let a network change and a mode change land at different
times). Now, if the deck has a third key row:

- MODE key — short press only, cycles a pending mode candidate (Buttons
  -> Satellite -> Companion, skipping Companion if not installed), shown
  as a colored label (BTN/SAT/CMP). Never commits anything by itself.
- NET key — short press only, toggles a pending DHCP/STATIC choice, shown
  as its actual label ("DHCP" or "STATIC"), not a generic "NET" text.
  Never commits anything by itself.
- SUBNET key — short press only, cycles a pending prefix length through
  SUBNET_OPTIONS (e.g. /24, /22, /16, /8). Only meaningful when STATIC is
  staged, but harmless to change regardless.
- The 4 IP octet keys (row 0) are editable ONLY while STATIC is staged —
  hold one to spin its value 0-255, release to lock it in. Locked/dimmed
  (ignored presses) while DHCP is staged, since there's nothing to build
  a static address out of in that case.
- GO key (bottom-right of the action row) — the ONLY key that actually
  applies anything. One press commits whatever's currently staged: a
  mode switch if the candidate differs from the active mode, and a
  network change if DHCP/STATIC differs from the current live state (or
  unconditionally re-pins STATIC with the currently staged octets/prefix
  if STATIC is staged, since re-pinning is idempotent and cheap). This
  exists specifically so a single mis-press of MODE or NET can't switch
  anything by itself — you set up the whole screen, then commit once.
- SSH key (between SUBNET and GO, decks with >=5 columns only) —
  hold-to-reveal, not always-on-display: shows a neutral "SSH" hint at
  rest, and only shows the actual random root password dpx-init-ssh.sh
  generated at first boot while a finger is physically holding the key
  down, reverting the instant it's released. Deliberately NOT shown
  anywhere on the web UI (that page has no login of its own) — this key
  is the only place it's ever revealed, so seeing it requires actually
  being at the device, not just LAN access. Blank once the user sets a
  real password via the web UI's SSH tab, which deletes the file this
  reads. SSH ships disabled with no hardcoded default credential at all.

This script never touches systemctl, netplan, or /etc/dpx-mode directly —
it shells out via `sudo` to dpx-buttonode-ui.py's `--apply-mode
<value>`/`--toggle-net`/`--pin-static <ip>[/prefix]` CLI subcommands (see
/etc/sudoers.d/dpx-splash, installed by install-deck-splash.sh), which is
where that logic actually lives. Keeps this process's own privilege
footprint at exactly `buttons` group membership — nothing more — even
though GO can trigger real system changes. Reads of live network state
(get_current_net_mode, get_primary_iface, get_current_prefix) are plain
unprivileged `ip` command output, duplicated from dpx-buttonode-ui.py's
own equivalents rather than imported — this is a separate process/venv
with no clean way to import a hyphenated-filename module, and these are
one-line-of-logic reads, not real business logic worth sharing.

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
from pathlib import Path

from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper
from PIL import Image, ImageDraw, ImageFont

PORT = 8080                  # dpx-buttonode-ui's port — shown alongside the IP
REFRESH_SECONDS = 5          # how often to re-check IP/hostname while idle
RETRY_SECONDS = 3            # how often to retry finding a deck if none present
REARM_SECONDS = 0.25         # ignore a new press this soon after the last one (contact bounce)
OCTET_STEP_SECONDS = 0.15    # how fast a held octet key spins its value
UI_SCRIPT = "/usr/local/bin/dpx-buttonode-ui.py"
MODE_FILE = Path("/etc/dpx-mode")
COMPANION_DIR = Path("/opt/companion")
INITIAL_SSH_PASSWORD_FILE = Path("/etc/dpx-initial-ssh-password")
MODE_ORDER = ["buttons", "satellite", "companion"]
MODE_LABELS = {"buttons": "BTN", "satellite": "SAT", "companion": "CMP"}
SUBNET_OPTIONS = [24, 22, 16, 8]
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


def get_primary_iface():
    """First real Ethernet interface name from sysfs. Mirrors
    dpx-buttonode-ui.py's get_primary_iface() — plain unprivileged read."""
    for p in sorted(Path("/sys/class/net").iterdir()):
        t_f = p / "type"
        a_f = p / "address"
        if not t_f.exists() or not a_f.exists():
            continue
        if t_f.read_text().strip() != "1":
            continue
        addr = a_f.read_text().strip()
        if re.match(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$", addr) and addr != "00:00:00:00:00:00":
            return p.name
    return "eth0"


def get_ip():
    out = run(["ip", "-4", "addr", "show", "scope", "global"])
    m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)/", out)
    return m.group(1) if m else None


def get_current_net_mode():
    """"dhcp" or "static", read live off the primary interface — mirrors
    the "dynamic" flag check dpx-buttonode-ui.py's get_net_info() does."""
    iface = get_primary_iface()
    out = run(["ip", "-4", "addr", "show", "dev", iface])
    return "dhcp" if "dynamic" in out else "static"


def get_current_prefix():
    iface = get_primary_iface()
    out = run(["ip", "-4", "addr", "show", "dev", iface, "scope", "global"])
    m = re.search(r"inet\s+\d+\.\d+\.\d+\.\d+/(\d+)", out)
    return int(m.group(1)) if m else 24


def get_mdns_name():
    """avahi publishes the system hostname by default, no override in this
    repo — so the mDNS name is just '<hostname>.local'."""
    return f"{socket.gethostname()}.local"


def companion_installed():
    """True on Full-variant images. Same check dpx-buttonode-ui.py's own
    companion_installed() makes (COMPANION_DIR.exists())."""
    return COMPANION_DIR.exists()


def get_current_mode():
    try:
        return MODE_FILE.read_text().strip()
    except Exception:
        return "buttons"


def get_initial_ssh_password():
    """The random password dpx-init-ssh.sh generated at first boot, or
    None once dpx-buttonode-ui.py's change_root_password() has deleted
    it (i.e. the user set a real password)."""
    try:
        return INITIAL_SSH_PASSWORD_FILE.read_text().strip() or None
    except Exception:
        return None


def next_mode(current):
    """Next candidate in the cycle, skipping Companion if not installed."""
    idx = MODE_ORDER.index(current) if current in MODE_ORDER else 0
    for _ in range(len(MODE_ORDER)):
        idx = (idx + 1) % len(MODE_ORDER)
        candidate = MODE_ORDER[idx]
        if candidate != "companion" or companion_installed():
            return candidate
    return current


def load_font(size):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


MODE_COLORS = {
    "buttons": (40, 90, 200),      # blue
    "satellite": (30, 150, 60),    # green
    "companion": (150, 40, 190),   # purple
}
NET_MODE_COLORS = {
    "dhcp": (40, 130, 200),        # blue
    "static": (200, 110, 20),      # orange
}
SUBNET_COLOR = (90, 90, 90)    # neutral gray — a setting, not a mode
GO_COLOR = (20, 175, 60)       # bright green — the one key that actually does something
SSH_PW_COLOR = (150, 130, 20)  # amber-brown — the first-boot initial root password, if still active
FLASH_COLOR = (255, 200, 0)    # amber flash — instant "press registered" feedback
EDIT_COLOR = (0, 170, 190)     # cyan — an octet currently being edited, not yet committed
DISABLED_FG = (110, 110, 110)  # dimmed text for octets locked while DHCP is staged


def render_key(deck, text, font_size=16, bg=(0, 0, 0), fg="white"):
    """One key, centered text, solid background — deliberately simple,
    hardcoded for exactly the fields we need (IP octet, hostname segment,
    action-button label). Not a general text-wrap engine.

    `bg` distinguishes the action keys (colored) from the plain info keys
    (black). `fg` dims octet text when editing is locked (DHCP staged).

    Shrinks the font until the text fits the key width (with a small
    margin) rather than letting a longer word (e.g. "STATIC") run off
    the edge.
    """
    image = PILHelper.create_key_image(deck)
    draw = ImageDraw.Draw(image)
    if bg != (0, 0, 0):
        draw.rectangle([(0, 0), image.size], fill=bg)
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
    draw.text(pos, text, font=font, fill=fg)
    return PILHelper.to_native_key_format(deck, image)


def blank_key(deck):
    image = PILHelper.create_key_image(deck)
    return PILHelper.to_native_key_format(deck, image)


def octet_key_indices(deck):
    """Key indices for the 4 IP-octet keys in row 0, or [] if the deck
    has fewer than 4 columns — there's no clean 1-key-per-octet mapping
    on a deck that small, so editing simply isn't offered there (same
    graceful-degradation approach as action_key_indices)."""
    rows, cols = deck.key_layout()
    if cols < 4:
        return []
    return [0, 1, 2, 3]


def draw_octet_key(deck, key, idx, live_octets, ip_edit, editable):
    """Render one octet key. idx is the octet's position (0-3), not the
    deck key index. Editing is only meaningful while STATIC is staged
    (`editable`) — when it's not, any in-progress edit is ignored and the
    live value is shown dimmed, signaling "you can't touch this right now"
    rather than silently doing nothing."""
    val = ip_edit.get(idx) if editable else None
    if val is not None:
        deck.set_key_image(key, render_key(deck, str(val), bg=EDIT_COLOR))
        return
    if idx < len(live_octets):
        text = live_octets[idx]
    elif idx == 0:
        text = "no"
    elif idx == 1:
        text = "IP"
    else:
        text = ""
    if not text:
        deck.set_key_image(key, blank_key(deck))
        return
    fg = "white" if editable else DISABLED_FG
    deck.set_key_image(key, render_key(deck, text, fg=fg))


def chunk_hostname(name, n):
    """Split 'dpx-buttonode-XXXX.local' across n keys on natural word
    boundaries (-, .), one whole word per key, each keeping its leading
    separator ("-buttonode", ".local") so the keys visually read as one
    connected string. render_key() shrinks the font to fit whatever lands
    on a key. Overflow (more segments than keys) folds into the last key.
    """
    segments = re.findall(r"[-.]?[^-.]+", name)
    if len(segments) > n:
        segments = segments[:n - 1] + ["".join(segments[n - 1:])]
    return segments + [""] * (n - len(segments))


def action_key_indices(deck):
    """Key indices for the action-row keys, or all-None if the deck
    doesn't have a third row (e.g. a 2-row Mini) — Phase 2/3 is simply
    unavailable on decks that small, not an error. GO is always the
    LAST key in the row (bottom-right), regardless of column count.
    ssh_key (shows the first-boot initial root password, if still
    active) sits between SUBNET and GO — only on decks with room for it
    (cols >= 5); on a narrower 3-row deck it'd collide with GO, so it's
    simply omitted (None) there rather than fought over."""
    rows, cols = deck.key_layout()
    if rows < 3:
        return None, None, None, None, None
    base = 2 * cols
    go_key = base + (cols - 1)
    ssh_key = base + 3 if cols >= 5 else None
    return base, base + 1, base + 2, ssh_key, go_key


def draw_mode_key(deck, key, mode_pending):
    deck.set_key_image(key, render_key(
        deck, MODE_LABELS[mode_pending], font_size=14, bg=MODE_COLORS[mode_pending]
    ))


def draw_net_key(deck, key, net_pending):
    deck.set_key_image(key, render_key(
        deck, net_pending.upper(), font_size=13, bg=NET_MODE_COLORS[net_pending]
    ))


def draw_subnet_key(deck, key, prefix_pending):
    deck.set_key_image(key, render_key(deck, f"/{prefix_pending}", font_size=15, bg=SUBNET_COLOR))


def draw_go_key(deck, key):
    deck.set_key_image(key, render_key(deck, "GO", font_size=18, bg=GO_COLOR))


def draw_ssh_key(deck, key):
    """Idle state for the SSH key — a neutral "SSH" hint, never the
    password itself. The password (see dpx-init-ssh.sh) only appears
    after this key is pressed, toggling back off on the next press (see
    make_key_callback's on_key) — not always-on-display. That's
    deliberate: the whole point is requiring someone to actually be at
    the device with a finger on the key, not just able to glance at the
    screen or reach the web UI over the LAN. Blank once the password's been
    superseded by a real one (the file gets deleted the moment
    dpx-buttonode-ui.py's change_root_password() succeeds — nothing left
    to reveal). Readable here because dpx-splash is already in the
    `buttons` group for HID access, and the file's group matches
    (root:buttons, 0640) — same permission model as everything else this
    process reads, no new privilege needed."""
    pw = get_initial_ssh_password()
    if pw:
        deck.set_key_image(key, render_key(deck, "SSH", font_size=15, bg=SSH_PW_COLOR))
    else:
        deck.set_key_image(key, blank_key(deck))


def draw_splash(deck, ip, mdns_name, state):
    """state = {"mode_pending", "net_pending", "prefix_pending", "ip_edit", "busy"}"""
    rows, cols = deck.key_layout()
    total = deck.key_count()
    mode_key, net_key, subnet_key, ssh_key, go_key = action_key_indices(deck)
    octet_keys = octet_key_indices(deck)
    live_octets = ip.split(".") if ip else []
    host_row = chunk_hostname(mdns_name, cols) if rows >= 2 else []
    editable = state["net_pending"] == "static"

    for i in range(total):
        r, c = divmod(i, cols)
        if i == mode_key:
            draw_mode_key(deck, i, state["mode_pending"])
        elif i == net_key:
            draw_net_key(deck, i, state["net_pending"])
        elif i == subnet_key:
            draw_subnet_key(deck, i, state["prefix_pending"])
        elif ssh_key is not None and i == ssh_key:
            draw_ssh_key(deck, i)
        elif i == go_key:
            draw_go_key(deck, i)
        elif r == 0 and octet_keys and c < 4:
            draw_octet_key(deck, i, c, live_octets, state["ip_edit"], editable)
        elif r == 0 and octet_keys and c == 4:
            deck.set_key_image(i, render_key(deck, f":{PORT}") if live_octets else blank_key(deck))
        elif r == 1 and c < len(host_row) and host_row[c]:
            deck.set_key_image(i, render_key(deck, host_row[c], font_size=12))
        else:
            deck.set_key_image(i, blank_key(deck))


def redraw_octets(deck, octet_keys, state):
    live_octets = (get_ip() or "").split(".")
    editable = state["net_pending"] == "static"
    for i, key in enumerate(octet_keys):
        draw_octet_key(deck, key, i, live_octets, state["ip_edit"], editable)


def run_privileged(args):
    """Shell out via sudo to the exact CLI subcommand on dpx-buttonode-ui.py
    that /etc/sudoers.d/dpx-splash whitelists. `args` is a list, e.g.
    ["--apply-mode", "satellite"] or ["--pin-static", "10.0.0.5/24"]. This
    process never runs the mode-switch/network logic itself or gains any
    privilege beyond `buttons` group membership — sudo is the only door.
    Returns (ok, msg).
    """
    try:
        r = subprocess.run(
            ["sudo", "-n", "/usr/bin/python3", UI_SCRIPT, *args],
            capture_output=True, text=True, timeout=30,
        )
        msg = (r.stdout or r.stderr).strip()
        ok = r.returncode == 0
        label = " ".join(args)
        print(f"dpx-deck-splash: {label} -> {msg or ('ok' if ok else 'failed')}")
        return ok, msg
    except Exception as e:
        print(f"dpx-deck-splash: {' '.join(args)} failed to run ({e})", file=sys.stderr)
        return False, str(e)


def execute_staged(deck, key, state):
    """The GO action: apply whatever's currently staged, as one combined
    operation. Runs the mode switch and the network change sequentially
    (not concurrently) — each is independently atomic on the server side,
    but either one can trigger Conflicts= and kill this process mid-way
    through the sequence. That's fine: whichever completes leaves the
    system in a valid, self-consistent state, it just means a single GO
    press might only get through the first of two staged changes if both
    were pending — pressing GO again afterward (once the splash service
    is back, if it survived) finishes the rest.

    Always clears state["busy"] and tries to redraw GO back to normal —
    guarded, since the process may already be dead by the time this runs.
    """
    try:
        current_mode = get_current_mode()
        if state["mode_pending"] != current_mode:
            run_privileged(["--apply-mode", state["mode_pending"]])

        if state["net_pending"] == "static":
            live = (get_ip() or "0.0.0.0").split(".")
            octets = [
                str(state["ip_edit"].get(i, int(live[i]) if i < len(live) else 0))
                for i in range(4)
            ]
            cidr = f"{'.'.join(octets)}/{state['prefix_pending']}"
            run_privileged(["--pin-static", cidr])
        elif get_current_net_mode() != "dhcp":
            run_privileged(["--toggle-net"])

        state["ip_edit"].clear()
    finally:
        state["busy"] = False
        try:
            draw_go_key(deck, key)
        except Exception:
            pass


def start_octet_edit(deck, key, idx, state, stop_events):
    """Begin spinning octet `idx`'s value while its key is held. Runs in
    its own thread, stepping every OCTET_STEP_SECONDS until `stop_events
    [key]` is set (on release). Starts from the live DHCP-assigned value
    the first time this octet is touched, then continues from wherever it
    was left if the same octet is held again later. Only called at all
    while STATIC is staged — see make_key_callback."""
    ev = threading.Event()
    stop_events[key] = ev
    if idx not in state["ip_edit"]:
        live = (get_ip() or "0.0.0.0").split(".")
        state["ip_edit"][idx] = int(live[idx]) if idx < len(live) else 0

    def loop():
        while True:
            state["ip_edit"][idx] = (state["ip_edit"][idx] + 1) % 256
            try:
                deck.set_key_image(key, render_key(deck, str(state["ip_edit"][idx]), bg=EDIT_COLOR))
            except Exception:
                return
            if ev.wait(OCTET_STEP_SECONDS):
                return  # stop signaled

    threading.Thread(target=loop, daemon=True).start()


def make_key_callback(state):
    """Returns a callback for deck.set_key_callback(). `state` is a small
    mutable dict shared with the caller — see draw_splash's docstring for
    its shape — so selections/edits survive across callback invocations
    and periodic IP/hostname redraws.

    Everything except GO and the octet keys is now a pure short-press
    toggle/cycle with zero side effects on the running system — MODE and
    NET only ever change state["mode_pending"]/state["net_pending"] and
    redraw. This is a deliberate v2 redesign: the first cut had MODE and
    NET each independently long-press-committing, which meant a network
    change and a mode change could land at different times with no way
    to review both before either took effect. Now nothing actually
    happens to the system until GO is pressed.

    Octet keys: hold to spin 0-255, release to lock in — but ONLY while
    STATIC is staged (state["net_pending"] == "static"); presses are
    silently ignored otherwise, since there's nothing to build a static
    address out of when DHCP is staged.

    GO: single press, immediate (fires on press, not release) — applies
    everything currently staged via execute_staged(), in a background
    thread so the HID callback isn't blocked for the several seconds a
    mode/network change can take.

    REARM_SECONDS guards against a too-fast repeat press being misread as
    a second gesture (hardware contact bounce), not against intentional
    rapid interaction.

    IMPORTANT, confirmed on hardware: when GO's action actually changes
    something, systemd kills this entire process (main PID) within a
    second or two — the new mode/net service starting triggers
    Conflicts=. There is no window afterward to draw a "done" screen; the
    Stream Deck's display isn't live video, it just holds whatever was
    last written. That's why the flash includes a checkmark rather than
    just a color swap — frozen "✓" reads as confirmation, a frozen bare
    block reads as broken.
    """
    last_press = {}
    stop_events = {}

    def on_key(deck, key, pressed):
        now = time.monotonic()
        mode_key, net_key, subnet_key, ssh_key, go_key = action_key_indices(deck)
        octet_keys = octet_key_indices(deck)

        if ssh_key is not None and key == ssh_key:
            # Press-to-toggle, not always-on-display: still requires an
            # actual finger on the physical key to reveal (not just able to
            # see the screen or reach the web UI over the LAN), but doesn't
            # require KEEPING it held — a finger resting on the key blocks
            # reading the very thing it's revealing. Confirmed on real
            # hardware 2026-08-28: hold-to-reveal was "very tricky" to
            # actually read. Acts on press only; release is a no-op so a
            # long press doesn't double-toggle.
            if not pressed:
                return
            pw = get_initial_ssh_password()
            if not pw:
                return  # nothing left to reveal — password already changed
            state["ssh_revealed"] = not state.get("ssh_revealed", False)
            if state["ssh_revealed"]:
                deck.set_key_image(key, render_key(deck, pw, font_size=13, bg=SSH_PW_COLOR))
            else:
                draw_ssh_key(deck, key)
            return

        if octet_keys and key in octet_keys:
            idx = octet_keys.index(key)
            if state["net_pending"] != "static":
                return  # editing locked unless STATIC is staged
            if pressed:
                start_octet_edit(deck, key, idx, state, stop_events)
            else:
                ev = stop_events.pop(key, None)
                if ev:
                    ev.set()
            return

        if not pressed:
            return  # MODE/NET/SUBNET/GO all act on press, nothing on release
        if now - last_press.get(key, 0) < REARM_SECONDS:
            return
        last_press[key] = now

        if key == mode_key:
            state["mode_pending"] = next_mode(state["mode_pending"])
            draw_mode_key(deck, key, state["mode_pending"])

        elif key == net_key:
            state["net_pending"] = "dhcp" if state["net_pending"] == "static" else "static"
            draw_net_key(deck, key, state["net_pending"])
            redraw_octets(deck, octet_keys, state)  # lock/unlock, dim/undim

        elif key == subnet_key:
            i = SUBNET_OPTIONS.index(state["prefix_pending"]) if state["prefix_pending"] in SUBNET_OPTIONS else 0
            state["prefix_pending"] = SUBNET_OPTIONS[(i + 1) % len(SUBNET_OPTIONS)]
            draw_subnet_key(deck, key, state["prefix_pending"])

        elif key == go_key:
            if state.get("busy"):
                return  # a previous GO is still in flight — ignore
            state["busy"] = True
            deck.set_key_image(key, render_key(deck, "GO ✓", font_size=15, bg=FLASH_COLOR))
            threading.Thread(target=execute_staged, args=(deck, key, state), daemon=True).start()

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
            # Everything pending starts at whatever's actually live — a
            # fresh session has no memory of any prior in-progress
            # selection, so defaulting to "current" avoids the readout
            # looking wrong (or, worse, staging a change nobody asked
            # for) the instant this starts up.
            state = {
                "mode_pending": get_current_mode(),
                "net_pending": get_current_net_mode(),
                "prefix_pending": get_current_prefix(),
                "ip_edit": {},
                "busy": False,
                "ssh_revealed": False,
            }
            deck.set_key_callback(make_key_callback(state))
            print(f"dpx-deck-splash: opened {deck.deck_type()} ({deck.key_count()} keys)")
            while True:
                ip = get_ip()
                if ip != last_ip:
                    draw_splash(deck, ip, get_mdns_name(), state)
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
