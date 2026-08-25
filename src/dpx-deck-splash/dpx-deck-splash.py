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
action buttons:

- MODE — a select-then-commit readout, not an instant switch. Short press
  advances a candidate (Buttons -> Satellite -> Companion, skipping
  Companion if not installed) shown as a colored label on the key
  (BTN/SAT/CMP) without touching anything yet; long press (held >=
  LONG_PRESS_SECONDS) commits — actually switches to whatever's currently
  shown. This exists because an instant single-tap switch is one
  mis-press away from killing this very service (see Conflicts= below)
  with no undo.
- NET — short press: immediate toggle, DHCP <-> static (going to static
  freezes whatever IP is currently DHCP-assigned). Long press: commits
  whatever's currently being edited via the octet keys below as a
  specific static IP, if anything's been edited — otherwise behaves the
  same as a short press.
- The 4 IP octet keys (row 0, when the deck has >=4 columns) double as
  editable fields: hold one down to spin its value 0-255 (auto-advances
  every OCTET_STEP_SECONDS while held, shown live in a distinct color),
  release to lock that octet in. Untouched octets keep showing the live
  DHCP value until NET is long-pressed to commit the combined result as a
  static IP (via --pin-static). No on-deck keyboard, so this is the only
  way to set a specific address from the device itself.

This script never touches systemctl, netplan, or /etc/dpx-mode directly —
it shells out via `sudo` to dpx-buttonode-ui.py's `--apply-mode
<value>`/`--toggle-net`/`--pin-static <ip>` CLI subcommands (see
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
from pathlib import Path

from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper
from PIL import Image, ImageDraw, ImageFont

PORT = 8080                  # dpx-buttonode-ui's port — shown alongside the IP
REFRESH_SECONDS = 5          # how often to re-check IP/hostname while idle
RETRY_SECONDS = 3            # how often to retry finding a deck if none present
LONG_PRESS_SECONDS = 1.0     # MODE/NET: held this long or more = commit, else = select/toggle
REARM_SECONDS = 0.25         # MODE/NET: ignore a new press this soon after the last release
OCTET_STEP_SECONDS = 0.15    # how fast a held octet key spins its value
UI_SCRIPT = "/usr/local/bin/dpx-buttonode-ui.py"
MODE_FILE = Path("/etc/dpx-mode")
COMPANION_DIR = Path("/opt/companion")
MODE_ORDER = ["buttons", "satellite", "companion"]
MODE_LABELS = {"buttons": "BTN", "satellite": "SAT", "companion": "CMP"}
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


def companion_installed():
    """True on Full-variant images. Same check dpx-buttonode-ui.py's own
    companion_installed() makes (COMPANION_DIR.exists()) — duplicated
    here rather than imported since this is a separate process/venv with
    no clean way to import a hyphenated-filename module, and it's a
    single one-line filesystem check, not real business logic."""
    return COMPANION_DIR.exists()


def get_current_mode():
    try:
        return MODE_FILE.read_text().strip()
    except Exception:
        return "buttons"


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
NET_COLOR = (200, 110, 20)     # orange — visually distinct from any MODE color
FLASH_COLOR = (255, 200, 0)    # amber flash — instant "press registered" feedback
EDIT_COLOR = (0, 170, 190)     # cyan — an octet currently being edited, not yet committed


def render_key(deck, text, font_size=16, bg=(0, 0, 0)):
    """One key, centered text, solid background — deliberately simple,
    hardcoded for exactly the fields we need (IP octet, hostname segment,
    action-button label). Not a general text-wrap engine.

    `bg` distinguishes the MODE/NET action keys (colored) from the plain
    info keys (black) — confirmed on hardware that leaving everything
    black made the action buttons impossible to tell apart from the
    IP/hostname display at a glance.

    Shrinks the font until the text fits the key width (with a small
    margin) rather than letting a longer word (e.g. "buttonode") run off
    the edge — segments are whole words now (see chunk_hostname), so
    lengths vary more than the old fixed-character-count chunking did.
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
    draw.text(pos, text, font=font, fill="white")
    return PILHelper.to_native_key_format(deck, image)


def blank_key(deck):
    image = PILHelper.create_key_image(deck)
    return PILHelper.to_native_key_format(deck, image)


def octet_key_indices(deck):
    """Key indices for the 4 editable IP-octet keys in row 0, or [] if the
    deck has fewer than 4 columns — there's no clean 1-key-per-octet
    mapping on a deck that small, so editing simply isn't offered there
    (same graceful-degradation approach as action_key_indices)."""
    rows, cols = deck.key_layout()
    if cols < 4:
        return []
    return [0, 1, 2, 3]


def draw_octet_key(deck, key, idx, live_octets, ip_edit):
    """Render one octet key: an in-progress edited value (cyan, from
    ip_edit) takes priority over the live DHCP-assigned value. idx is the
    octet's position (0-3), not the deck key index."""
    val = ip_edit.get(idx)
    if val is not None:
        deck.set_key_image(key, render_key(deck, str(val), bg=EDIT_COLOR))
        return
    if idx < len(live_octets):
        deck.set_key_image(key, render_key(deck, live_octets[idx]))
    elif idx == 0:
        deck.set_key_image(key, render_key(deck, "no"))
    elif idx == 1:
        deck.set_key_image(key, render_key(deck, "IP"))
    else:
        deck.set_key_image(key, blank_key(deck))


def chunk_hostname(name, n):
    """Split 'dpx-buttonode-XXXX.local' across n keys on natural word
    boundaries (-, .), one whole word per key — not a fixed character
    count. Each segment (after the first) keeps its leading separator
    ("-buttonode", ".local") so the keys visually read as one connected
    string rather than unrelated words — confirmed on hardware that
    dropping the separator entirely reads as confusing, not just plain.
    render_key() shrinks the font to fit whatever lands on a key, so a
    longer segment like "-buttonode" still renders whole instead of
    getting chopped mid-word (old bug: fixed 6-char slices produced
    "dpx-bu"/"ttonod"/"e-2199"). If there are more segments than keys,
    the overflow gets folded into the last key rather than silently
    dropped.
    """
    segments = re.findall(r"[-.]?[^-.]+", name)
    if len(segments) > n:
        segments = segments[:n - 1] + ["".join(segments[n - 1:])]
    return segments + [""] * (n - len(segments))


def action_key_indices(deck):
    """Key indices for the MODE and NET action buttons, or (None, None) if
    the deck doesn't have a third row to put them in (e.g. a 2-row Mini) —
    Phase 2/3 is simply unavailable on decks that small, not an error."""
    rows, cols = deck.key_layout()
    if rows < 3:
        return None, None
    return 2 * cols, 2 * cols + 1


def draw_mode_key(deck, key, mode_candidate):
    """Redraw just the MODE key showing the current (not-yet-committed)
    candidate — its own function since this needs to be called both from
    the full draw_splash() and standalone whenever the candidate changes
    on a short press, without redrawing the whole deck."""
    deck.set_key_image(key, render_key(
        deck, MODE_LABELS[mode_candidate], font_size=14, bg=MODE_COLORS[mode_candidate]
    ))


def draw_splash(deck, ip, mdns_name, state):
    """state = {"mode_candidate": <mode>, "ip_edit": {octet_idx: value}}"""
    rows, cols = deck.key_layout()
    total = deck.key_count()
    mode_key, net_key = action_key_indices(deck)
    octet_keys = octet_key_indices(deck)
    live_octets = ip.split(".") if ip else []
    host_row = chunk_hostname(mdns_name, cols) if rows >= 2 else []

    for i in range(total):
        r, c = divmod(i, cols)
        if i == mode_key:
            draw_mode_key(deck, i, state["mode_candidate"])
        elif i == net_key:
            deck.set_key_image(i, render_key(deck, "NET", font_size=14, bg=NET_COLOR))
        elif r == 0 and octet_keys and c < 4:
            draw_octet_key(deck, i, c, live_octets, state["ip_edit"])
        elif r == 0 and octet_keys and c == 4:
            deck.set_key_image(i, render_key(deck, f":{PORT}") if live_octets else blank_key(deck))
        elif r == 1 and c < len(host_row) and host_row[c]:
            deck.set_key_image(i, render_key(deck, host_row[c], font_size=12))
        else:
            deck.set_key_image(i, blank_key(deck))


def run_privileged(args):
    """Shell out via sudo to the exact CLI subcommand on dpx-buttonode-ui.py
    that /etc/sudoers.d/dpx-splash whitelists. `args` is a list, e.g.
    ["--apply-mode", "satellite"] or ["--toggle-net"]. This process never
    runs the mode-switch/network-toggle logic itself or gains any
    privilege beyond `buttons` group membership — sudo is the only door,
    and every command it can open onto is enumerated exactly in the
    sudoers file, nothing wildcarded on the mode/toggle commands. Returns
    (ok, msg).
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


def do_action(deck, key, args, redraw_on_failure, state):
    """Run a privileged action and reconcile the key's on-screen state
    with what actually happened. If it succeeds, the process usually gets
    killed within a second or two anyway (the new mode/net service
    restart triggers Conflicts=) — the flash drawn on press just stays
    frozen as the last image, which is fine, it reads as confirmation. If
    it FAILS (e.g. no gateway detected for NET), nothing about the
    running state changes and this process survives — leaving the flash
    up in that case would be a false positive, so `redraw_on_failure()`
    (a zero-arg callable) restores the key's normal look. Guarded in
    try/except since the deck handle can legitimately disappear mid-call
    if the action DID succeed and killed us before this line runs.

    Always clears state["busy"] when done (confirmed on hardware this
    matters: a mode/net action can take several seconds — poll loops,
    service restarts — and without a busy guard a second press landing
    mid-action fires a second concurrent privileged call that races the
    first one instead of being ignored).
    """
    try:
        ok, _ = run_privileged(args)
        if not ok:
            try:
                redraw_on_failure()
            except Exception:
                pass
    finally:
        state["busy"] = False


def start_octet_edit(deck, key, idx, state, stop_events):
    """Begin spinning octet `idx`'s value while its key is held. Runs in
    its own thread, stepping every OCTET_STEP_SECONDS until `stop_events
    [key]` is set (on release). Starts from the live DHCP-assigned value
    the first time this octet is touched, then continues from wherever it
    was left if the same octet is held again later."""
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
    mutable dict shared with the caller so selections/edits survive
    across callback invocations and periodic IP/hostname redraws:
    {"mode_candidate": <one of MODE_ORDER>, "ip_edit": {octet_idx: value}}

    Three groups of keys, three interaction patterns:

    OCTET keys (row 0, cols 0-3, if the deck is wide enough) — hold to
    spin that octet's value 0-255 (start_octet_edit, above), release to
    lock it in at whatever it landed on. Nothing is applied to the system
    yet — this only edits state["ip_edit"].

    MODE — select-then-commit, distinguished by press duration:
    - press: record the timestamp.
    - release held < LONG_PRESS_SECONDS: short press, advance the
      candidate to the next mode and redraw just that key. Nothing
      applied yet.
    - release held >= LONG_PRESS_SECONDS: long press, commit — apply via
      --apply-mode <candidate> in a background thread.

    NET — press duration decides short-toggle vs. commit-edited-IP:
    - release held < LONG_PRESS_SECONDS: short press, plain DHCP<->static
      toggle (--toggle-net), same as Phase 2's first cut.
    - release held >= LONG_PRESS_SECONDS AND at least one octet has been
      edited: commit the edited IP as a specific static address
      (--pin-static <ip>), combining edited octets with the live value
      for any untouched ones. With nothing edited, a long press just
      behaves like a short one — there's nothing else it could mean.

    REARM_SECONDS guards against a too-fast repeat press being misread as
    a new gesture (hardware contact bounce), not against intentional
    rapid interaction — kept short so cycling MODE or spinning an octet
    doesn't feel sluggish.

    IMPORTANT, confirmed on hardware: when a commit/toggle SUCCEEDS,
    systemd kills this entire process (main PID) within a second or two
    — the new mode/net service starting triggers Conflicts=. There is no
    window afterward to draw a "done" screen; the Stream Deck's display
    isn't live video, it just holds whatever was last written. That's why
    every commit flash includes a checkmark rather than just a color swap
    — frozen "✓" reads as confirmation, a frozen bare block reads as
    broken.
    """
    press_started = {}
    last_release = {}
    stop_events = {}

    def on_key(deck, key, pressed):
        now = time.monotonic()
        mode_key, net_key = action_key_indices(deck)
        octet_keys = octet_key_indices(deck)

        if octet_keys and key in octet_keys:
            idx = octet_keys.index(key)
            if pressed:
                start_octet_edit(deck, key, idx, state, stop_events)
            else:
                ev = stop_events.pop(key, None)
                if ev:
                    ev.set()
            return

        if key == mode_key:
            if pressed:
                if now - last_release.get(key, 0) < REARM_SECONDS:
                    return
                press_started[key] = now
                return
            # release
            start = press_started.pop(key, None)
            last_release[key] = now
            if start is None:
                return
            held = now - start
            if held >= LONG_PRESS_SECONDS:
                if state.get("busy"):
                    return  # a previous commit/toggle is still in flight — ignore
                state["busy"] = True
                candidate = state["mode_candidate"]
                deck.set_key_image(key, render_key(
                    deck, f"{MODE_LABELS[candidate]} ✓", font_size=12, bg=FLASH_COLOR
                ))
                threading.Thread(
                    target=do_action,
                    args=(deck, key, ["--apply-mode", candidate],
                          lambda: draw_mode_key(deck, key, state["mode_candidate"]), state),
                    daemon=True,
                ).start()
            else:
                state["mode_candidate"] = next_mode(state["mode_candidate"])
                draw_mode_key(deck, key, state["mode_candidate"])
            return

        if key == net_key:
            if pressed:
                if now - last_release.get(key, 0) < REARM_SECONDS:
                    return
                press_started[key] = now
                return
            # release
            start = press_started.pop(key, None)
            last_release[key] = now
            if start is None:
                return
            if state.get("busy"):
                return  # a previous commit/toggle is still in flight — ignore
            held = now - start
            revert = lambda: deck.set_key_image(key, render_key(deck, "NET", font_size=14, bg=NET_COLOR))
            if held >= LONG_PRESS_SECONDS and state["ip_edit"]:
                state["busy"] = True
                live = (get_ip() or "0.0.0.0").split(".")
                final = [
                    str(state["ip_edit"].get(i, int(live[i]) if i < len(live) else 0))
                    for i in range(4)
                ]
                ip_str = ".".join(final)
                state["ip_edit"].clear()
                deck.set_key_image(key, render_key(deck, "NET ✓", font_size=12, bg=FLASH_COLOR))
                threading.Thread(
                    target=do_action, args=(deck, key, ["--pin-static", ip_str], revert, state), daemon=True
                ).start()
            else:
                # write_networkd_config() also restarts whichever mode
                # service /etc/dpx-mode currently names, which can trigger
                # the same Conflicts=-kills-us-mid-flight situation as
                # MODE above — but NET frequently no-ops (e.g. no gateway
                # detected) and leaves this process alive, so do_action()
                # reverts the key on failure instead of leaving a
                # false-positive checkmark.
                state["busy"] = True
                deck.set_key_image(key, render_key(deck, "NET ✓", font_size=12, bg=FLASH_COLOR))
                threading.Thread(
                    target=do_action, args=(deck, key, ["--toggle-net"], revert, state), daemon=True
                ).start()

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
            # Candidate starts at whatever mode is actually active — a
            # fresh dpx-deck-splash session (new open) has no memory of
            # any in-progress selection from before, so defaulting to
            # "current" rather than always "buttons" avoids the readout
            # looking wrong the instant it starts up.
            state = {"mode_candidate": get_current_mode(), "ip_edit": {}, "busy": False}
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
