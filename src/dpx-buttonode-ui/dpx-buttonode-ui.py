#!/usr/bin/env python3
"""
dpx-buttonode-ui — DPX device configuration web interface
Installed: /usr/local/bin/dpx-buttonode-ui.py
Service:   dpx-buttonode-ui.service
Port:      8080

Zero external dependencies — uses Python 3 stdlib only.
"""

import ctypes
import ctypes.util
import http.server
import json
import os
import re
import socket
import subprocess
import sys
import tarfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

PORT = 8080
HOSTNAME_MARKER = "/var/lib/dpx-hostname-set"
BUTTONS_API    = "http://localhost:3040"
NETWORKD_DIR   = Path("/etc/systemd/network")
DPX_NET_FILE   = NETWORKD_DIR / "05-dpx-eth.network"   # 05- beats Netplan's 10-
DPX_NET_OLD    = NETWORKD_DIR / "10-dpx-eth.network"   # remove if exists (old name)
NETPLAN_DIR    = Path("/etc/netplan")
DPX_NETPLAN    = NETPLAN_DIR / "99-dpx-override.yaml"  # highest priority, beats armbian 10-
MODE_FILE      = Path("/etc/dpx-mode")              # 'buttons', 'satellite', or 'companion'
INITIAL_SSH_PASSWORD_FILE = Path("/etc/dpx-initial-ssh-password")  # written by dpx-init-ssh.sh; cleared once the user sets their own
SAT_CONFIG     = Path("/etc/dpx-satellite.conf")    # our persistent satellite config
SAT_BOOT_CFG   = Path("/boot/satellite-config")     # satellite's one-shot import file
SATELLITE_API  = "http://localhost:9999"             # satellite REST API
COMPANION_DIR  = Path("/opt/companion")              # present on full images only
COMPANION_PORT = 8000                                # companion web UI port
DASHBOARD_SERVICE = "dpx-dashboard"                  # Companion Dashboard kiosk display
MODE_COLORS = {"buttons": "#3fb950", "satellite": "#58a6ff", "companion": "#e3b341"}


def mode_color_for(mode):
    return MODE_COLORS.get(mode, "#3fb950")


def ram_color_for(pct):
    return "#f85149" if pct >= 90 else ("#e3b341" if pct >= 70 else "#3fb950")

# ── On-device updates ────────────────────────────────────────────────────────
GITHUB_API  = "https://api.github.com"
GITHUB_REPO = "dubpixel/dpx_buttonode"
UI_SCRIPT_PATH          = Path("/usr/local/bin/dpx-buttonode-ui.py")
DECK_SPLASH_SCRIPT_PATH = Path("/usr/local/bin/dpx-deck-splash.py")
BOOT_STATE_FILE = Path("/var/lib/dpx-buttonode-ui.boot-state")  # crash-loop detector, see __main__
UPDATE_SATELLITE_LOG    = Path("/var/log/dpx-update-satellite.log")
UPDATE_SATELLITE_STATUS = Path("/var/lib/dpx-update-satellite.status")  # running/ok/failed
UPDATE_COMPANION_LOG    = Path("/var/log/dpx-update-companion.log")
UPDATE_COMPANION_STATUS = Path("/var/lib/dpx-update-companion.status")

# ── TTL cache ──────────────────────────────────────────────────────────────────
# Subprocess calls (systemctl, lsusb, avahi-browse) are expensive.
# Cache results with a short TTL so rapid page loads don't re-fork.
_cache: dict = {}
_cache_lock = threading.Lock()

def _cached(key, ttl, fn):
    """Return cached value for key, or call fn(), cache it for ttl seconds."""
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(key)
        if entry and now < entry[1]:
            return entry[0]
    val = fn()
    with _cache_lock:
        _cache[key] = (val, now + ttl)
    return val

# ── System helpers ─────────────────────────────────────────────────────────────

def run(cmd):
    """Run a command list, return (stdout, stderr, returncode).
    Returns ("" , "command not found", 127) if the binary doesn't exist.
    """
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except FileNotFoundError:
        return "", f"command not found: {cmd[0]}", 127


def get_hostname():
    return socket.gethostname()


def get_mac():
    """Return MAC of first real Ethernet interface (sysfs, always available)."""
    for p in sorted(Path("/sys/class/net").iterdir()):
        t_f = p / "type"
        a_f = p / "address"
        if not t_f.exists() or not a_f.exists():
            continue
        if t_f.read_text().strip() != "1":
            continue
        addr = a_f.read_text().strip()
        if re.match(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$", addr) and addr != "00:00:00:00:00:00":
            return addr
    return "unknown"


def get_ip():
    out, _, _ = run(["ip", "-4", "addr", "show", "scope", "global"])
    m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)/", out)
    return m.group(1) if m else "unknown"


def get_gateway():
    """Return current default gateway from the live routing table."""
    out, _, _ = run(["ip", "-4", "route", "show", "default"])
    m = re.search(r"via\s+(\d+\.\d+\.\d+\.\d+)", out)
    return m.group(1) if m else ""


def get_ip_cidr():
    """Return live IP with actual prefix length (e.g. 10.50.0.44/22)."""
    iface = get_primary_iface()
    out, _, _ = run(["ip", "-4", "addr", "show", "dev", iface, "scope", "global"])
    m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+/\d+)", out)
    return m.group(1) if m else get_ip() + "/24"


def svc_active(name):
    return _cached(f"svc:{name}", 5, lambda: run(["systemctl", "is-active", "--quiet", name])[2] == 0)


def nmcli_available():
    _, _, rc = run(["nmcli", "--version"])
    return rc == 0


def networkd_active():
    _, _, rc = run(["systemctl", "is-active", "--quiet", "systemd-networkd"])
    return rc == 0


def netplan_available():
    return Path("/usr/sbin/netplan").exists() or Path("/usr/bin/netplan").exists()


def get_primary_iface():
    """First real Ethernet interface name from sysfs."""
    for p in sorted(Path("/sys/class/net").iterdir()):
        t_f = p / "type"; a_f = p / "address"
        if not t_f.exists() or not a_f.exists(): continue
        if t_f.read_text().strip() != "1": continue
        addr = a_f.read_text().strip()
        if re.match(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$", addr) and addr != "00:00:00:00:00:00":
            return p.name
    return "eth0"


def get_net_info():
    """Return dict: nmcli, networkd (bools), mode, iface, ip_cidr, gateway, dns."""
    iface = get_primary_iface()
    info  = {"nmcli": False, "networkd": False, "iface": iface,
             "mode": "dhcp", "ip_cidr": get_ip_cidr(),
             "gateway": get_gateway(), "dns": "8.8.8.8"}

    if nmcli_available():
        info["nmcli"] = True
        out, _, rc = run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", "--active"])
        if rc != 0: return info
        conn = ""
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and "ethernet" in parts[1].lower():
                conn = parts[0]; break
        if not conn: return info
        info["conn"] = conn
        out2, _, _ = run(["nmcli", "-t", "-f",
                          "ipv4.method,ipv4.addresses,ipv4.gateway,ipv4.dns",
                          "connection", "show", conn])
        for line in out2.splitlines():
            k, _, v = line.partition(":")
            if k == "ipv4.method" and v == "manual": info["mode"] = "static"
            elif k == "ipv4.addresses" and v: info["ip_cidr"] = v
            elif k == "ipv4.gateway": info["gateway"] = v
            elif k == "ipv4.dns" and v: info["dns"] = v.split(",")[0]
        return info

    if networkd_active():
        info["networkd"] = True
        # Read mode from the live interface — "dynamic" = DHCP lease, no "dynamic" = static
        iface_out, _, _ = run(["ip", "-4", "addr", "show", "dev", iface])
        if "dynamic" in iface_out:
            info["mode"] = "dhcp"
        elif re.search(r"inet\s+\d", iface_out):
            info["mode"] = "static"
        # For static: read configured values from our override file if present
        if info["mode"] == "static" and DPX_NETPLAN.exists():
            txt = DPX_NETPLAN.read_text()
            m = re.search(r"-\s+(\d+\.\d+\.\d+\.\d+/\d+)", txt)
            if m: info["ip_cidr"] = m.group(1)
            m = re.search(r"via:\s+(\S+)", txt)
            if m: info["gateway"] = m.group(1)
        return info

    return info


def write_networkd_config(iface, mode, ip_cidr=None, gateway=None, dns="8.8.8.8"):
    """Apply network config. Uses Netplan if available (Armbian), raw networkd otherwise."""
    # 09- sorts before Netplan's 10- wildcard, giving us priority for end0
    DPX_STATIC   = Path(f"/etc/systemd/network/09-dpx-{iface}.network")
    # Netplan's wildcard DHCP file — must be removed so static can win
    RUN_WILDCARD = Path("/run/systemd/network/10-netplan-all-eth-interfaces.network")

    if netplan_available():
        # Clean up any leftover files from previous approaches
        for stale in [Path("/etc/systemd/network/05-dpx-eth.network"),
                      Path("/etc/systemd/network/10-dpx-eth.network"),
                      Path("/etc/systemd/network/10-netplan-all-eth-interfaces.network")]:
            if stale.exists():
                stale.unlink()
        if mode == "static":
            DPX_STATIC.parent.mkdir(parents=True, exist_ok=True)
            DPX_STATIC.write_text(
                f"[Match]\nName={iface}\n\n"
                f"[Network]\nAddress={ip_cidr}\nGateway={gateway}\nDNS={dns}\n"
            )
            # Remove the wildcard DHCP file. Without it, only our 09- file
            # matches end0 — networkd applies static cleanly after restart.
            if RUN_WILDCARD.exists():
                RUN_WILDCARD.unlink()
        else:  # dhcp
            # Remove our static override
            if DPX_STATIC.exists():
                DPX_STATIC.unlink()
            # Restore Netplan's /run/ files (brings back wildcard DHCP)
            run(["netplan", "generate"])
        run(["systemctl", "restart", "systemd-networkd"])
    else:
        # Raw networkd fallback for boards without Netplan
        NETWORKD_DIR.mkdir(parents=True, exist_ok=True)
        if DPX_NET_OLD.exists():
            DPX_NET_OLD.unlink()
        if mode == "dhcp":
            content = f"[Match]\nName={iface}\n\n[Network]\nDHCP=yes\n"
        else:
            content = (f"[Match]\nName={iface}\n\n"
                       f"[Network]\nAddress={ip_cidr}\nGateway={gateway}\nDNS={dns}\n")
        DPX_NET_FILE.write_text(content)
        run(["networkctl", "reconfigure", iface])
    # Poll until the new IP appears (up to 5s)
    target_ip = ip_cidr.split("/")[0] if ip_cidr else None
    for _ in range(10):
        time.sleep(0.5)
        out, _, _ = run(["ip", "-4", "addr", "show", "dev", iface])
        if mode == "dhcp" or (target_ip and target_ip in out):
            break
    # Re-announce mDNS on the new address
    run(["systemctl", "reload-or-restart", "avahi-daemon"])
    time.sleep(0.5)
    # Reconnect whichever mode service is actually active — used to be a
    # hardcoded restart of bitfocus-buttons-usb-relay from when Buttons was
    # always the default; wrong now that Satellite/Companion can be active.
    active_svc = {
        "buttons": "bitfocus-buttons-usb-relay",
        "satellite": "satellite",
        "companion": "companion",
    }.get(get_dpx_mode(), "bitfocus-buttons-usb-relay")
    run(["systemctl", "restart", active_svc])
    # Restart ourselves — the server socket breaks when the IP changes.
    # Use systemd-run so this continues after our process exits.
    run(["systemd-run", "--no-block", "--quiet",
         "systemctl", "restart", "dpx-buttonode-ui"])


def write_nmcli_config(iface, mode, ip_cidr=None, gateway=None, dns="8.8.8.8"):
    """Apply network config through NetworkManager. `nmcli connection
    modify` writes the change straight to the connection's on-disk
    profile (/etc/NetworkManager/system-connections/*.nmconnection), so
    unlike the networkd path there's no separate config file to manage —
    the same command that applies it live is what makes it persist."""
    out, _, _ = run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", "--active"])
    conn = ""
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and "ethernet" in parts[1].lower():
            conn = parts[0]
            break
    if not conn:
        return
    if mode == "dhcp":
        run(["nmcli", "connection", "modify", conn,
             "ipv4.method", "auto",
             "ipv4.addresses", "",
             "ipv4.gateway", "",
             "ipv4.dns", ""])
    else:
        run(["nmcli", "connection", "modify", conn,
             "ipv4.method", "manual",
             "ipv4.addresses", ip_cidr,
             "ipv4.gateway", gateway,
             "ipv4.dns", dns])
    run(["nmcli", "connection", "up", conn])
    run(["systemctl", "reload-or-restart", "avahi-daemon"])
    active_svc = {
        "buttons": "bitfocus-buttons-usb-relay",
        "satellite": "satellite",
        "companion": "companion",
    }.get(get_dpx_mode(), "bitfocus-buttons-usb-relay")
    run(["systemctl", "restart", active_svc])
    run(["systemd-run", "--no-block", "--quiet",
         "systemctl", "restart", "dpx-buttonode-ui"])


def apply_net_config(iface, mode, ip_cidr=None, gateway=None, dns="8.8.8.8"):
    """Persist network config through whichever backend actually manages
    this interface. Raspberry Pi OS defaults to NetworkManager; Armbian
    defaults to systemd-networkd/Netplan. Writing networkd files on an
    nmcli-managed box doesn't survive reboot — NetworkManager reasserts
    its own connection profile on boot, reverting straight back to DHCP
    (dpx#14) — so the two paths need picking, not just one used blindly."""
    if nmcli_available():
        write_nmcli_config(iface, mode, ip_cidr, gateway, dns)
    else:
        write_networkd_config(iface, mode, ip_cidr, gateway, dns)


def toggle_net():
    """Flip DHCP<->static. No argument needed — a caller with no way to
    type an address (a deck keypress) should have nothing to get wrong.

    Going TO static freezes whatever IP is currently DHCP-assigned as the
    new static config — not a restore of some previously-saved value.
    Simpler and more broadly useful: it works the very first time, on a
    device that's never been static before, instead of failing with
    "nothing saved" (the original design required a prior static config
    to exist before you could ever toggle to static at all — confirmed on
    hardware that this is confusing on a fresh device). Going back to
    DHCP just requests a fresh lease; toggling to static again later
    freezes whatever that new lease happens to be, which is more useful
    than replaying stale historical values anyway.

    Returns (ok: bool, message: str).
    """
    iface = get_primary_iface()
    current = get_net_info()
    if current["mode"] == "dhcp":
        if not current.get("gateway"):
            return False, "No gateway detected — can't safely pin a static config"
        apply_net_config(iface, "static", current["ip_cidr"], current["gateway"], current["dns"])
        return True, f"Pinned static {current['ip_cidr']}"
    apply_net_config(iface, "dhcp")
    return True, "Switched to DHCP"


def pin_static(cidr_str):
    """Apply a specific, fully user-chosen static IP address (all four
    octets, plus an optional /prefix), keeping the CURRENTLY DETECTED
    gateway/DNS unchanged — the deck's stage-then-GO flow (hold an octet
    key to spin its value, cycle the SUBNET key for a prefix, press GO to
    commit) calls this with the address it built up. `cidr_str` is
    "ip" or "ip/prefix"; if no prefix is given, falls back to whatever
    prefix is currently live. Unlike --apply-mode's three enumerated
    sudoers values, sudoers can only glob-match this argument loosely
    (see install-deck-splash.sh) — this function, using the same
    validate_ip() the web UI's own network form uses plus a prefix range
    check, is the real gate. Returns (ok, msg).
    """
    ip_str, _, prefix_str = cidr_str.partition("/")
    if not validate_ip(ip_str):
        return False, "Invalid IP address"
    iface = get_primary_iface()
    current = get_net_info()
    if not current.get("gateway"):
        return False, "No gateway detected — can't safely pin a static config"
    if prefix_str:
        if not (prefix_str.isdigit() and 0 <= int(prefix_str) <= 32):
            return False, "Invalid subnet prefix"
        prefix = prefix_str
    else:
        prefix = current["ip_cidr"].split("/")[-1] if "/" in current["ip_cidr"] else "24"
    ip_cidr = f"{ip_str}/{prefix}"
    apply_net_config(iface, "static", ip_cidr, current["gateway"], current["dns"])
    return True, f"Pinned static {ip_cidr}"


def get_usb_devices():
    return _cached("usb_devices", 5, _get_usb_devices_raw)

def _get_usb_devices_raw():
    out, _, _ = run(["lsusb"])
    return [l for l in out.splitlines() if l.strip()]


def buttons_reachable():
    """TCP-level check that Buttons is listening on port 3040."""
    import socket as _sock
    try:
        s = _sock.create_connection(("127.0.0.1", 3040), timeout=2)
        s.close()
        return True
    except OSError:
        return False


def find_streamdeck_usb_path():
    """Return sysfs port name (e.g. '1-1.2') for first Elgato Stream Deck (vendor 0fd9)."""
    for vendor_file in sorted(Path("/sys/bus/usb/devices").glob("*/idVendor")):
        try:
            if vendor_file.read_text().strip() == "0fd9":
                return vendor_file.parent.name
        except Exception:
            continue
    return None


def udev_retrigger():
    """Nudge udev into reprocessing already-enumerated USB/HID devices,
    without a bus-level reset or physical replug. Fixes a specific failure
    mode confirmed live 2026-08-26: the kernel had hid-generic bound to a
    Stream Deck the whole time (dmesg showed zero new events), but its
    /dev/hidraw* node had been dropped and never got recreated after heavy
    mode-switch churn — invisible to libusb-based consumers (deck-splash,
    Satellite) but fatal to Companion's hidraw-only surface module.
    Cheap and non-disruptive, so it's always worth trying before the
    unbind/bind fallback below, which goes dark and previously needed an
    actual physical replug to fully recover from in some cases."""
    run(["udevadm", "trigger", "--subsystem-match=hid"])
    run(["udevadm", "trigger", "--subsystem-match=usb"])
    time.sleep(1)


def _has_hidraw(port_path):
    """True if the USB device at `port_path` (e.g. '1-1') has a live
    /dev/hidraw* node under any of its interfaces. Used to decide whether
    udev_retrigger() alone already fixed things, so the disruptive
    unbind/bind fallback can be skipped when it's not actually needed."""
    return any(Path("/sys/bus/usb/devices").glob(f"{port_path}*/**/hidraw/hidraw*"))


def usb_power_cycle(port_path, delay=2):
    """Unbind then rebind a USB port. Deck goes dark for `delay` seconds.
    Always tries the gentle udev_retrigger() first — see its docstring —
    and skips the disruptive unbind/bind entirely if that alone already
    restored a working hidraw node, so the deck only goes dark when the
    lighter fix genuinely wasn't enough (e.g. the USB error -110 case
    documented in ROADMAP.md that needed a real physical replug even
    after this same unbind/bind)."""
    udev_retrigger()
    if _has_hidraw(port_path):
        return True, ""
    unbind = Path("/sys/bus/usb/drivers/usb/unbind")
    bind   = Path("/sys/bus/usb/drivers/usb/bind")
    try:
        unbind.write_text(port_path)
        time.sleep(delay)
        bind.write_text(port_path)
        return True, ""
    except Exception as e:
        return False, str(e)


def discover_buttonodes():
    return _cached("buttonodes", 10, _discover_buttonodes_raw)

def _discover_buttonodes_raw():
    """Return list of dpx-buttonode instances found via avahi-browse.
    Requires avahi-daemon running and the _dpx-buttonode._tcp service registered.
    Each entry: {hostname, addr, port, is_self}
    """
    # -p parseable, -t terminate when done, -r resolve addresses
    out, _, rc = run(["avahi-browse", "-p", "-t", "-r", "_dpx-buttonode._tcp"])
    if rc != 0:
        return []
    me   = get_hostname().lower()
    seen = set()
    nodes = []
    for line in out.splitlines():
        if not line.startswith("="):
            continue
        parts = line.split(";")
        if len(parts) < 9:
            continue
        proto    = parts[2]   # IPv4 / IPv6
        hostname = parts[6].rstrip(".").removesuffix(".local")
        addr     = parts[7]
        port     = parts[8]
        if proto != "IPv4" or hostname in seen:
            continue
        seen.add(hostname)
        nodes.append({"hostname": hostname, "addr": addr,
                      "port": port, "is_self": hostname.lower() == me})
    return sorted(nodes, key=lambda n: (not n["is_self"], n["hostname"]))


def validate_hostname(name):
    return bool(name and len(name) <= 63 and
                re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?$", name))


def validate_ip(ip):
    parts = ip.split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


def esc(s):
    """Minimal HTML escaping for user-visible values."""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


# ── CSS ────────────────────────────────────────────────────────────────────────

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f1117;color:#e1e4e8;min-height:100vh}
a{color:#388bfd;text-decoration:none}
.hdr{background:#161b22;border-bottom:1px solid #30363d;padding:14px 24px;display:flex;align-items:center;gap:10px}
.hdr h1{font-size:17px;font-weight:700;color:#f0f6ff;letter-spacing:-.3px}
.tag{background:#1f6feb;color:#fff;font-size:10px;padding:2px 8px;border-radius:12px;font-weight:700;letter-spacing:.3px}
.statusbar{position:sticky;top:0;z-index:20;background:#0d1117;border-bottom:1px solid #30363d;padding:6px 24px;display:flex;gap:18px;align-items:center;font-family:ui-monospace,monospace;font-size:11px;color:#8b949e;overflow-x:auto;white-space:nowrap}
.statusbar b{font-weight:700}
.nav{background:#161b22;border-bottom:1px solid #21262d;padding:0 24px;display:flex;gap:2px;overflow-x:auto}
.nav a{display:inline-block;padding:10px 14px;font-size:13px;color:#8b949e;border-bottom:2px solid transparent;white-space:nowrap}
.nav a.on,.nav a:hover{color:#f0f6ff;border-bottom-color:#1f6feb}
.wrap{max-width:880px;margin:0 auto;padding:24px 16px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(148px,1fr));gap:10px;margin-bottom:20px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px}
.lbl{font-size:10px;color:#8b949e;text-transform:uppercase;letter-spacing:.5px;margin-bottom:5px}
.val{font-size:17px;font-weight:700;color:#f0f6ff;font-family:ui-monospace,monospace;word-break:break-all}
.val.on{color:#3fb950}.val.off{color:#f85149}
.sec{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:20px;margin-bottom:14px}
.sec h2{font-size:12px;font-weight:700;color:#8b949e;text-transform:uppercase;letter-spacing:.6px;margin-bottom:14px;padding-bottom:10px;border-bottom:1px solid #21262d}
.row{margin-bottom:12px}
.row label{display:block;font-size:12px;color:#8b949e;margin-bottom:4px}
input[type=text]{width:100%;background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px 12px;color:#f0f6ff;font-size:14px;font-family:ui-monospace,monospace}
input[type=text]:focus{outline:none;border-color:#1f6feb;box-shadow:0 0 0 3px #1f6feb22}
.btn{background:#21262d;border:1px solid #30363d;color:#f0f6ff;padding:8px 16px;border-radius:6px;font-size:13px;cursor:pointer;display:inline-block;margin-right:6px;font-family:inherit}
.btn-p{background:#1f6feb;border-color:#1f6feb}.btn-p:hover{background:#388bfd}
.btn-w{background:#9e6a03;border-color:#9e6a03}.btn-w:hover{background:#b07d12}
.alert{padding:10px 14px;border-radius:6px;font-size:13px;margin-bottom:16px;line-height:1.5}
.a-ok{background:#0d2a1a;border:1px solid #3fb950;color:#3fb950}
.a-err{background:#2a0d0d;border:1px solid #f85149;color:#f85149}
.a-warn{background:#2a1d00;border:1px solid #9e6a03;color:#d4a017}
.radios{display:flex;gap:16px;margin-bottom:14px}
.radios label{display:flex;align-items:center;gap:6px;cursor:pointer;font-size:14px}
.usb{list-style:none}
.usb li{font-family:ui-monospace,monospace;font-size:12px;color:#8b949e;padding:5px 0;border-bottom:1px solid #21262d}
.usb li:last-child{border:none}
.badge{display:inline-block;font-size:11px;padding:2px 8px;border-radius:10px;font-weight:600}
.badge-on{background:#0d2a1a;color:#3fb950}.badge-off{background:#21262d;color:#8b949e}
code{background:#21262d;padding:2px 6px;border-radius:4px;font-size:12px;font-family:ui-monospace,monospace}
.note{font-size:12px;color:#8b949e;line-height:1.6;margin-bottom:14px}
.footer{border-top:1px solid #21262d;margin-top:24px;padding:10px 16px;text-align:center;font-size:11px;color:#484f58;font-family:ui-monospace,monospace;letter-spacing:.2px}
"""

# ── Page template ──────────────────────────────────────────────────────────────

def page(content, tab="status", alert="", alert_cls="a-ok"):
    hostname = esc(get_hostname())
    al = (f'<div class="alert {alert_cls}">{alert}</div>' if alert else "")
    tabs = [
        ("status",   "/",         "Status"),
        ("hostname", "/hostname", "Hostname"),
        ("network",  "/network",  "Network"),
        ("devices",  "/devices",  "Devices"),
        ("nodes",    "/nodes",    "Nodes"),
        ("mode",     "/mode",     "Mode"),
        ("ssh",      "/ssh",      "SSH"),
        ("updates",  "/updates",  "Updates"),
    ]
    nav = "".join(
        f'<a href="{u}" class="{"on" if t == tab else ""}">{n}</a>'
        for t, u, n in tabs
    )
    bld = get_build_info()
    variant_tag = bld.get("variant", "lite")
    companion_part = f' &nbsp;&middot;&nbsp; companion {esc(bld["companion_version"])}' if variant_tag == "full" else ""
    footer = (
        f'<div class="footer">'
        f'buttons {esc(bld["buttons_version"])}'
        f' &nbsp;&middot;&nbsp; satellite {esc(bld["satellite_version"])}'
        f'{companion_part}'
        f' &nbsp;&middot;&nbsp; {esc(bld["git_branch"])}@{esc(bld["git_commit"])}'
        f' &nbsp;&middot;&nbsp; built {esc(bld["build_date"])}'
        f'</div>'
    )

    # Persistent status bar — version, mode, RAM — carries through every tab,
    # not just the Status page. Sticky so it stays visible while scrolling.
    mode = get_dpx_mode()
    ram_str, ram_pct = get_ram_usage_human()
    dash_suffix = " +D" if (dashboard_installed() and dashboard_enabled()) else ""
    statusbar = (
        f'<div class="statusbar">'
        f'<span><b>v{esc(bld["dpx_version"])}</b> [{esc(variant_tag)}]</span>'
        f'<span>MODE: <b style="color:{mode_color_for(mode)}">{esc(mode).upper()}{dash_suffix}</b></span>'
        f'<span>RAM: <b style="color:{ram_color_for(ram_pct)}">{esc(ram_str)}</b></span>'
        f'</div>'
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{hostname} — dpx-buttonode-ui</title>
<link rel="icon" type="image/png" href="/favicon.png">
<style>{CSS}</style>
</head>
<body>
<div class="hdr"><h1>⯁ {hostname}</h1><span class="tag">dpx-buttonode-ui</span></div>
{statusbar}
<nav class="nav">{nav}</nav>
<div class="wrap">{al}{content}</div>
{footer}
</body>
</html>"""


# ── Page renderers ─────────────────────────────────────────────────────────────

def get_uptime_human():
    """System uptime as e.g. '2d 4h 12m', from /proc/uptime."""
    try:
        with open("/proc/uptime") as f:
            secs = int(float(f.read().split()[0]))
    except (OSError, ValueError, IndexError):
        return "unknown"
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    parts = [f"{days}d"] if days else []
    if days or hours:
        parts.append(f"{hours}h")
    parts.append(f"{mins}m")
    return " ".join(parts)


def get_ram_usage_human():
    """(used/total string, percent used) from /proc/meminfo. MemAvailable
    (not MemFree) is used for 'used' so page cache doesn't read as pressure."""
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.strip().split()[0])
        total_kb = info["MemTotal"]
        avail_kb = info["MemAvailable"]
        used_kb  = total_kb - avail_kb
        pct = round(used_kb / total_kb * 100) if total_kb else 0
        return f"{used_kb / 1024:.0f}MB / {total_kb / 1024:.0f}MB", pct
    except (OSError, ValueError, KeyError):
        return "unknown", 0


def render_status(alert="", alert_cls="a-ok"):
    ip      = esc(get_ip())
    mac     = esc(get_mac())
    host    = esc(get_hostname())
    bs      = svc_active("bitfocus-buttons-usb-relay")
    av      = svc_active("avahi-daemon")
    net     = get_net_info()
    usb     = get_usb_devices()
    mode    = get_dpx_mode()
    ss      = svc_active("satellite")
    cs      = svc_active("companion")
    uptime  = esc(get_uptime_human())
    ram_str, ram_pct = get_ram_usage_human()
    ram_color = ram_color_for(ram_pct)
    # Mode card: label + active service indicator + detail line
    if mode == "satellite":
        sat_host, sat_port = get_satellite_config()
        mode_detail = f'<div style="font-size:11px;color:#8b949e;margin-top:4px">{esc(sat_host) or "unconfigured"}:{esc(sat_port)}</div>' if sat_host else '<div style="font-size:11px;color:#8b949e;margin-top:4px">companion not configured</div>'
        svc_label = f'<div class="val {"on" if ss else "off"}" style="font-size:13px">satellite {"active" if ss else "inactive"}</div>'
    elif mode == "companion":
        mode_detail = f'<div style="font-size:11px;color:#8b949e;margin-top:4px"><a href="http://{esc(get_ip())}:{COMPANION_PORT}" target="_blank" style="color:#e3b341">open :8000 ↗</a></div>'
        svc_label = f'<div class="val {"on" if cs else "off"}" style="font-size:13px">companion {"active" if cs else "inactive"}</div>'
    else:
        mode_detail = ""
        svc_label   = f'<div class="val {"on" if bs else "off"}" style="font-size:13px">buttons {"active" if bs else "inactive"}</div>'

    mode_color = mode_color_for(mode)
    mode_card = f"""  <div class="card"><div class="lbl">Mode</div>
    <div class="val" style="font-size:16px;font-weight:700;color:{mode_color}">{mode.upper()}</div>
    {svc_label}
    {mode_detail}</div>"""

    grid = f"""
<div class="grid">
  <div class="card" style="grid-column:span 2"><div class="lbl">Hostname</div>
    <div class="val" style="font-size:15px">{host}</div></div>
  <div class="card" style="grid-column:span 2"><div class="lbl">IP Address</div>
    <div class="val" style="font-size:15px">{ip}</div></div>
  <div class="card"><div class="lbl">MAC</div>
    <div class="val" style="font-size:12px">{mac}</div></div>
  <div class="card"><div class="lbl">Network</div>
    <div class="val" style="font-size:14px">{esc(net['mode']).upper()}</div></div>
{mode_card}
  <div class="card"><div class="lbl">mDNS</div>
    <div class="val {'on' if av else 'off'}">{'active' if av else 'inactive'}</div></div>
  <div class="card"><div class="lbl">Uptime</div>
    <div class="val" style="font-size:14px">{uptime}</div></div>
  <div class="card"><div class="lbl">RAM</div>
    <div class="val" style="font-size:14px;color:{ram_color}">{esc(ram_str)}</div></div>
</div>
<div class="sec"><h2>USB Devices</h2>
  <ul class="usb">
    {''.join(f'<li>{esc(d)}</li>' for d in usb) if usb else '<li style="color:#8b949e">No USB devices detected</li>'}
  </ul>
</div>"""
    return page(grid, "status", alert, alert_cls)


def render_hostname(val="", alert="", alert_cls="a-ok"):
    cur  = esc(get_hostname())
    disp = esc(val) if val else cur
    body = f"""
<div class="sec"><h2>Change Hostname</h2>
  <p class="note">
    Current hostname: <code>{cur}</code><br>
    mDNS address: <code>{cur}.local</code><br>
    The new hostname is applied immediately and persists across reboots.
  </p>
  <form method="POST" action="/hostname">
    <div class="row">
      <label>New hostname (letters, numbers, hyphens — no spaces)</label>
      <input type="text" name="hostname" value="{disp}"
             placeholder="dpx-buttonode-XXXX"
             pattern="[a-zA-Z0-9][a-zA-Z0-9\\-]{{0,62}}" required>
    </div>
    <button type="submit" class="btn btn-p">Apply</button>
    <a href="/" class="btn">Cancel</a>
  </form>
</div>"""
    return page(body, "hostname", alert, alert_cls)


def render_network(alert="", alert_cls="a-ok"):
    net = get_net_info()

    if not net["nmcli"] and not net["networkd"]:
        body = f"""
<div class="sec"><h2>Network Settings</h2>
  <div class="alert a-warn">
    Network manager not detected.<br>
    Current IP: <code>{esc(net['ip_cidr'])}</code>
  </div>
  <a href="/" class="btn">Back</a>
</div>"""
        return page(body, "network", alert, alert_cls)

    sv      = "" if net["mode"] == "static" else 'style="display:none"'
    backend = (f'<p class="note">Using <code>systemd-networkd</code> — '
               f'writes to <code>{DPX_NET_FILE}</code></p>'
               if net["networkd"] else "")
    body = f"""
<div class="sec"><h2>Network Settings</h2>
  {backend}
  <div class="alert a-warn" style="margin-bottom:14px">
    ⚠ Do not disable IPv6 — it breaks DHCP on Armbian.
  </div>
  <form method="POST" action="/network">
    <div class="radios">
      <label><input type="radio" name="mode" value="dhcp"
               {"checked" if net["mode"] != "static" else ""}
               onchange="tog(this)"> DHCP (automatic)</label>
      <label><input type="radio" name="mode" value="static"
               {"checked" if net["mode"] == "static" else ""}
               onchange="tog(this)"> Static IP</label>
    </div>
    <div id="sf" {sv}>
      <div class="row"><label>IP / prefix (e.g. 192.168.1.100/24)</label>
        <input type="text" name="ip" value="{esc(net['ip_cidr'])}" placeholder="192.168.1.100/24"></div>
      <div class="row"><label>Default gateway</label>
        <input type="text" name="gateway" value="{esc(net['gateway'])}" placeholder="192.168.1.1"></div>
      <div class="row"><label>DNS server</label>
        <input type="text" name="dns" value="{esc(net['dns'])}" placeholder="8.8.8.8"></div>
    </div>
    <button type="submit" class="btn btn-p">Apply</button>
    <a href="/" class="btn">Cancel</a>
  </form>
</div>
<script>function tog(e){{document.getElementById('sf').style.display=e.value==='static'?'':'none'}}</script>"""
    return page(body, "network", alert, alert_cls)


def render_devices(alert="", alert_cls="a-ok"):
    usb    = get_usb_devices()
    api_ok = buttons_reachable()
    deck   = find_streamdeck_usb_path()
    badge  = (
        '<span class="badge badge-on">● listening on :3040</span>'
        if api_ok else
        '<span class="badge badge-off">○ not reachable on :3040</span>'
    )
    deck_info = (
        f'Found at USB port <code>{esc(deck)}</code>'
        if deck else
        'No Elgato Stream Deck detected on USB'
    )
    body = f"""
<div class="sec"><h2>Connected USB Devices</h2>
  <ul class="usb">
    {''.join(f'<li>{esc(d)}</li>' for d in usb) if usb else '<li style="color:#8b949e">No USB devices detected</li>'}
  </ul>
</div>
<div class="sec"><h2>Stream Deck</h2>
  <p class="note">{deck_info}</p>
  <p class="note" style="margin-bottom:14px">
    Power cycles the USB port — deck goes dark for ~2 seconds then reconnects.
  </p>
  <form method="POST" action="/power-cycle-deck" style="display:inline">
    <button type="submit" class="btn btn-p" {'disabled' if not deck else ''}>&#9211; Power Cycle Deck</button>
  </form>
</div>
<div class="sec"><h2>Buttons Service</h2>
  <p class="note">
    bitfocus-buttons-usb-relay {badge}<br>
    Restart the service to reset the relay process (does not power cycle the deck).
  </p>
  <form method="POST" action="/restart-buttons" style="display:inline">
    <button type="submit" class="btn btn-w">↺ Restart Buttons</button>
  </form>
  <a href="/" class="btn">Back</a>
</div>"""
    return page(body, "devices", alert, alert_cls)


DASHBOARD_RAM_WARN_MB = 1024   # X11 + openbox + Electron kiosk realistically needs
                               # several hundred MB RSS; below this, expect trouble.
                               # rockpi-s (466MB total) is the board that prompted this.


def total_ram_mb():
    """Total system RAM in MB, from /proc/meminfo. Returns None if unreadable."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def dashboard_section():
    """Companion Dashboard toggle — independent of mode, only shown if
    install-dashboard.sh actually installed the unit on this image."""
    if not dashboard_installed():
        return ""
    on = dashboard_enabled()
    badge = (
        '<span class="badge badge-on">● running</span>' if on else
        '<span class="badge badge-off">○ stopped</span>'
    )
    action = "disable" if on else "enable"
    label  = "⏻ Turn Off" if on else "⏻ Turn On"
    ram = total_ram_mb()
    ram_warning = ""
    if ram is not None and ram < DASHBOARD_RAM_WARN_MB:
        ram_warning = (
            f'<p class="note" style="color:#c33">'
            f'⚠ This board reports {ram}MB RAM — Dashboard\'s X11/Electron kiosk '
            f'stack usually needs 1GB+ to run reliably alongside a mode service. '
            f'It may crash-loop or hang on enable. Enable at your own risk.</p>'
        )
    return f"""
<div class="sec"><h2>Companion Dashboard</h2>
  <p class="note">
    Opt-in kiosk display {badge}<br>
    Runs alongside whatever mode (Buttons/Satellite/Companion) is active.
    Needs an attached HDMI display. Configure which Companion instance it
    points at from its own on-screen settings after enabling.
  </p>
  {ram_warning}
  <form method="POST" action="/dashboard" style="display:inline">
    <input type="hidden" name="action" value="{action}">
    <button type="submit" class="btn {'btn-w' if on else 'btn-p'}">{label}</button>
  </form>
  {'<form method="POST" action="/dashboard/fullscreen" style="display:inline"><button type="submit" class="btn">⛶ Toggle Fullscreen</button></form>' if on else ''}
  {f'<a href="http://{esc(get_ip())}/control" target="_blank" class="btn" style="text-decoration:none;display:inline-block">⚙ Remote Config ↗</a>' if on else ''}
</div>"""


def render_nodes(alert="", alert_cls="a-ok"):
    nodes = discover_buttonodes()
    me    = get_hostname()
    rows  = ""
    for n in nodes:
        self_tag = (
            ' <span class="badge badge-on" style="font-size:9px;vertical-align:middle">THIS NODE</span>'
            if n["is_self"] else ""
        )
        border = "#1f6feb" if n["is_self"] else "#30363d"
        action = (
            '<span style="color:#8b949e;font-size:12px">this device</span>'
            if n["is_self"] else
            f'<a href="http://{esc(n["addr"])}:{esc(n["port"])}/" '
            f'class="btn btn-p" style="font-size:12px" target="_blank">Open UI →</a>'
        )
        rows += f"""
<div style="background:#161b22;border:1px solid {border};border-radius:8px;padding:14px;
            margin-bottom:10px;display:flex;align-items:center;justify-content:space-between;gap:12px">
  <div>
    <div style="font-weight:700;color:#f0f6ff;margin-bottom:3px">
      {esc(n['hostname'])}{self_tag}</div>
    <div style="font-size:12px;color:#8b949e;font-family:ui-monospace,monospace">{esc(n['addr'])}</div>
  </div>
  {action}
</div>"""

    if not rows:
        rows = '<p class="note">No dpx-buttonodes found on this network.<br>Make sure avahi-daemon is running on all units.</p>'

    body = f"""
<div class="sec"><h2>Nodes on This Network</h2>
  {rows}
  <div style="margin-top:14px">
    <a href="/nodes" class="btn">↺ Rescan</a>
    <a href="/" class="btn">Back</a>
  </div>
</div>"""
    return page(body, "nodes", alert, alert_cls)


# ── Mode helpers ───────────────────────────────────────────────────────────────

def get_dpx_mode():
    """Return current mode: 'buttons', 'satellite', or 'companion'."""
    try:
        return MODE_FILE.read_text().strip()
    except Exception:
        return "buttons"


def companion_installed():
    """True if full Companion is installed (Full image variant)."""
    return COMPANION_DIR.exists()


def dashboard_installed():
    """True if Companion Dashboard's systemd unit was installed by
    install-dashboard.sh (both variants ship it — presence of the unit
    file, not the mode, is what gates the toggle)."""
    return Path(f"/etc/systemd/system/{DASHBOARD_SERVICE}.service").exists()


def dashboard_enabled():
    """True if the Dashboard kiosk display is currently running. Dashboard
    is independent of the Buttons/Satellite/Companion mode system — it
    runs alongside whatever mode is active, not instead of it."""
    return svc_active(DASHBOARD_SERVICE)


def set_dashboard_enabled(enable):
    """Toggle the Dashboard kiosk display on/off. Does not touch
    switch_mode()/SVC_MAP/Conflicts= — Dashboard has no relationship to
    the mode system at all."""
    if enable:
        run(["systemctl", "enable", "--now", DASHBOARD_SERVICE])
    else:
        run(["systemctl", "disable", "--now", DASHBOARD_SERVICE])


def dashboard_toggle_fullscreen():
    """Synthesize an F11 keypress into the Dashboard kiosk's X session via
    xdotool. Works because dpx-buttonode-ui and dpx-dashboard both run as
    root on the same machine — X's -nolisten tcp (in the xinit ExecStart)
    only blocks *network* X connections, not local ones via DISPLAY=:0.
    Lets someone toggle fullscreen from the web UI without a keyboard
    physically attached to the kiosk display."""
    env = dict(os.environ, DISPLAY=":0")
    try:
        r = subprocess.run(["xdotool", "key", "F11"], env=env,
                            capture_output=True, text=True, timeout=5)
        return r.returncode == 0, (r.stderr.strip() or "ok")
    except Exception as e:
        return False, str(e)


def switch_mode(new_mode):
    """Switch operating mode to 'buttons', 'satellite', or 'companion'.
    Stops+disables the old service, enables+starts the new one, persists
    the choice to MODE_FILE. Shared by the web UI's /mode handler and the
    --apply-mode CLI subcommand (used by external callers like the deck
    splash service). Returns (ok: bool, message: str).
    """
    valid = {"buttons", "satellite", "companion"}
    if new_mode not in valid:
        return False, "Invalid mode"
    if new_mode == "companion" and not companion_installed():
        return False, "Full Companion not installed — flash the Full image variant"
    current = get_dpx_mode()
    SVC_MAP = {
        "buttons":   "bitfocus-buttons-usb-relay",
        "satellite": "satellite",
        "companion": "companion",
    }
    old_svc = SVC_MAP.get(current, "bitfocus-buttons-usb-relay")
    new_svc = SVC_MAP[new_mode]
    if new_mode == current:
        # The persisted mode alone doesn't guarantee its service is
        # actually running -- confirmed live 2026-08-29: a crash (or a
        # reboot after one) can leave MODE_FILE saying e.g. "companion"
        # while companion.service is dead. Blindly no-opping here meant
        # there was no way to relaunch it -- not from the web UI, and not
        # from the deck's GO key, since both funnel through this
        # function. Only skip if it's genuinely already up.
        if svc_active(new_svc):
            return True, f"Already in {new_mode} mode"
    # If switching TO satellite, stage the config before starting
    if new_mode == "satellite":
        host, port = get_satellite_config()
        if host:
            write_satellite_config(host, port)
    run(["systemctl", "stop",    old_svc])
    run(["systemctl", "disable", old_svc])
    run(["systemctl", "enable",  new_svc])
    # Nudge udev before handing the deck to any HID-consuming mode.
    # Confirmed live 2026-08-29: heavy mode-switch churn can leave the
    # kernel holding the Stream Deck bound but with its /dev/hidraw* node
    # missing -- invisible to libusb-based consumers (Satellite, this
    # process itself) but fatal to Companion's hidraw-only surface
    # driver. Previously only fixed by manually hitting /power-cycle-deck
    # after the fact; baking it into every switch means it's already
    # fixed by the time the new mode's service starts, not something
    # that has to be noticed and triggered separately.
    udev_retrigger()
    _, err, rc = run(["systemctl", "start", new_svc])
    if rc != 0:
        return False, f"Failed to start {new_svc}: {err}"
    MODE_FILE.write_text(new_mode + "\n")
    LABELS = {"buttons": "Buttons USB Relay", "satellite": "Companion Satellite", "companion": "Bitfocus Companion"}
    return True, f"Switched to {LABELS[new_mode]}"


# ── SSH management ───────────────────────────────────────────────────────────
#
# Ships with SSH DISABLED by default (see dpx-buttonode.pkr.hcl) — this is
# the only management surface for it, and this web UI itself has NO
# authentication of its own (plain HTTP, no login, reachable by anyone on
# the LAN). That matters a lot here: without the check below, "enable SSH
# from the web UI" would be *worse* than the old always-on root/1234
# default — it'd let anyone on the LAN turn SSH on with a password of
# their own choosing, no guessing required at all. So every action here
# requires proving you already know the CURRENT root password first,
# verified directly against /etc/shadow (this process runs as root, so it
# can read that itself — no separate secret needs storing). That keeps the
# security bar at "you already have root," same as SSH access always was,
# just reachable through the browser too.

_libcrypt = ctypes.CDLL(ctypes.util.find_library("crypt") or "libcrypt.so.1")
_libcrypt.crypt.restype = ctypes.c_char_p
_libcrypt.crypt.argtypes = [ctypes.c_char_p, ctypes.c_char_p]


def _crypt(password, salt):
    """Direct binding to the system's real crypt(3) via ctypes — the
    stdlib `crypt` module was removed in Python 3.13 (PEP 594), which
    Raspberry Pi OS Trixie ships (Armbian's older base still has it).
    Hand-rolling a hash algorithm isn't an option here: Debian/Raspberry
    Pi OS default to yescrypt, not sha512crypt, so only the real libcrypt
    can verify it correctly regardless of which scheme was used. Confirmed
    live 2026-08-30 — this was silently crash-looping dpx-buttonode-ui on
    every Raspberry Pi OS build all session (ModuleNotFoundError on
    startup), never a boot-sequence problem at all."""
    result = _libcrypt.crypt(password.encode(), salt.encode())
    return result.decode() if result else None


def _get_shadow_hash(username):
    """Direct /etc/shadow read — the stdlib `spwd` module was removed in
    the same Python 3.13 release as `crypt` (same PEP, same batch).
    Requires root, which this service already runs as."""
    try:
        with open("/etc/shadow") as f:
            for line in f:
                fields = line.split(":")
                if fields[0] == username:
                    return fields[1]
    except OSError:
        pass
    return None


def verify_root_password(candidate):
    """True if `candidate` matches root's actual login password, checked
    against /etc/shadow directly."""
    try:
        stored_hash = _get_shadow_hash("root")
        if not stored_hash or stored_hash in ("*", "!", "!!", ""):
            return False  # locked/no-password account — never treat as a match
        return _crypt(candidate, stored_hash) == stored_hash
    except Exception:
        return False


def ssh_enabled():
    """True if SSH is actually reachable right now. Checking only
    ssh.service is not enough: Ubuntu ships ssh.socket enabled alongside
    it, and socket activation means systemd listens on :22 and lazily
    starts ssh.service on the first connection attempt regardless of the
    service's own enabled/active state. Confirmed live 2026-08-28 — a
    freshly-flashed device with ssh.service "disabled" was still fully
    SSH-reachable the whole time. Either unit being active means SSH is
    reachable."""
    return svc_active("ssh.socket") or svc_active("ssh.service")


def get_initial_ssh_password():
    """The random password dpx-init-ssh.sh generated at first boot, or
    None once the user has set their own (the file is deleted the moment
    change_root_password() succeeds — see below)."""
    try:
        return INITIAL_SSH_PASSWORD_FILE.read_text().strip() or None
    except Exception:
        return None


def set_ssh_enabled(enable):
    """Enabling only ever needs ssh.service — starting it directly works
    fine regardless of ssh.socket's state. Disabling must stop BOTH
    ssh.service and ssh.socket, or the socket unit keeps systemd
    listening on :22 and transparently starts ssh.service on demand,
    silently undoing the disable (see ssh_enabled())."""
    if enable:
        run(["systemctl", "enable", "--now", "ssh.service"])
    else:
        run(["systemctl", "disable", "--now", "ssh.socket"])
        run(["systemctl", "disable", "--now", "ssh.service"])


def change_root_password(new_password):
    """Sets root's password via chpasswd. Rejects newlines outright — the
    "user:password\\n" stdin format chpasswd expects means an embedded
    newline could inject a second line/command into that stream.
    """
    if "\n" in new_password or "\r" in new_password:
        return False, "Password cannot contain newlines"
    if len(new_password) < 8:
        return False, "Password must be at least 8 characters"
    r = subprocess.run(
        ["chpasswd"], input=f"root:{new_password}\n", text=True, capture_output=True
    )
    if r.returncode != 0:
        return False, (r.stderr.strip() or "Failed to set password")
    # The generated initial password is now stale/wrong — stop showing it
    # anywhere (web UI, deck splash) the moment a real one is set.
    try:
        INITIAL_SSH_PASSWORD_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    return True, "Root password updated"



RELEASE_FILE = Path("/etc/dpx-buttonode-release")

def get_build_info():
    return _cached("build_info", 3600, _get_build_info_raw)

def _get_build_info_raw():
    """Return dict of build metadata from /etc/dpx-buttonode-release.
    Keys: dpx_version, buttons_version, git_branch, git_commit, build_date.
    Falls back to 'unknown' for any missing key.
    """
    info = {"dpx_version": "unknown", "buttons_version": "unknown",
            "satellite_version": "unknown", "companion_version": "unknown",
            "variant": "lite",
            "git_branch": "unknown", "git_commit": "unknown", "build_date": "unknown"}
    try:
        for line in RELEASE_FILE.read_text().splitlines():
            line = line.strip()
            if "=" in line:
                k, _, v = line.partition("=")
                key = k.strip().lower()
                if key in info:
                    info[key] = v.strip()
    except Exception:
        pass
    return info


def invalidate_build_info_cache():
    """Force the next get_build_info() call to re-read RELEASE_FILE instead
    of serving the 1h-stale cached dict — call after anything writes to
    /etc/dpx-buttonode-release (version bumps from an applied update)."""
    with _cache_lock:
        _cache.pop("build_info", None)


# ── On-device update checks ──────────────────────────────────────────────────
# Four independent components, four independent check functions — they hit
# different repos with different tag formats and answer genuinely different
# questions ("is there a newer dpx_buttonode build" vs "is there a newer
# Buttons .deb in our mirror" vs two separate upstream Bitfocus projects), so
# there's no shared abstraction beyond _github_get()/_cached() below. Each
# returns {"current", "latest", "available", "checked_at"} and never raises —
# a network failure just means "unknown"/not-available, not a broken page.

def _github_get(path):
    """GET a GitHub API path, return parsed JSON or None on ANY failure
    (network, timeout, non-200, bad JSON, rate-limited). Unauthenticated —
    60 req/hr limit, comfortably enough for four checks capped at one real
    request per hour each via _cached(). GitHub requires a User-Agent header
    or it 403s outright, easy to miss."""
    try:
        req = urllib.request.Request(
            f"{GITHUB_API}{path}",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "dpx-buttonode-ui"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def _extract_dpx_version(tag_name):
    """Release tags look like dpx-buttnode-<buttons_version>-build<dpx_version>
    (note: historical tag spelling "buttnode" predates this project's rename
    to "buttonode" — tolerate both, don't try to fix old tags retroactively).
    Returns the trailing build version, or None if the tag doesn't match at
    all (treated as "no update detected" by callers — fail safe, not loud).
    """
    m = re.search(r"-build(.+)$", tag_name or "")
    return m.group(1) if m else None


def _check_dpx_update():
    current = get_build_info().get("dpx_version", "unknown")
    data = _github_get(f"/repos/{GITHUB_REPO}/releases/latest")
    tag = data.get("tag_name") if data else None
    latest = _extract_dpx_version(tag)
    return {
        "current": current, "latest": latest or "unknown",
        "available": bool(latest and latest != current),
        "tag": tag, "checked_at": time.time(),
    }


def _check_buttons_update():
    current = get_build_info().get("buttons_version", "unknown")
    data = _github_get(f"/repos/{GITHUB_REPO}/releases/tags/buttons-deb-mirror")
    latest = None
    if data:
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            # bitfocus-buttons-usb-relay-headless_<version>_arm64.tar.gz
            m = re.search(r"_([^_]+)_arm64\.tar\.gz$", name)
            if m:
                latest = m.group(1)
                break
    return {
        "current": current, "latest": latest or "unknown",
        "available": bool(latest and latest != current),
        "checked_at": time.time(),
    }


def _check_satellite_update():
    current = get_build_info().get("satellite_version", "unknown")
    data = _github_get("/repos/bitfocus/companion-satellite/releases/latest")
    tag = data.get("tag_name") if data else None
    latest = tag.lstrip("v") if tag else None
    return {
        "current": current, "latest": latest or "unknown",
        "available": bool(latest and latest != current),
        "checked_at": time.time(),
    }


def _check_companion_update():
    """Companion's real release source is a Bitfocus-hosted API, not
    GitHub Releases. Found live 2026-08-29 checking why this always
    reported "unknown": bitfocus/companion-pi (which install-companion.sh
    downloads its *installer* from) has zero GitHub releases of its own
    -- the actual build artifacts are served from api.bitfocus.io, per
    companion-pi's own update-prompt/main.py (the interactive version
    picker update.sh invokes)."""
    current_raw = get_build_info().get("companion_version", "unknown")
    # Our stored version includes the build hash (e.g.
    # "5.0.4+9717-stable-a69c14dec2"); the API only gives the bare
    # semver ("v5.0.4") -- compare on just the leading X.Y.Z.
    m = re.match(r"(\d+\.\d+\.\d+)", current_raw)
    current = m.group(1) if m else current_raw
    try:
        req = urllib.request.Request(
            "https://api.bitfocus.io/v1/product/companion/packages",
            headers={"Accept": "application/json", "User-Agent": "dpx-buttonode-ui"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        data = None
    latest, latest_published = None, None
    for pkg in (data or {}).get("packages", []):
        if pkg.get("target") != "linux-arm64-tgz":
            continue
        published = pkg.get("published", "")
        if latest_published is None or published > latest_published:
            latest_published, latest = published, (pkg.get("version") or "").lstrip("v")
    return {
        "current": current_raw, "latest": latest or "unknown",
        "available": bool(latest and latest != current),
        "checked_at": time.time(),
    }


UPDATE_CHECKS = {
    "dpx": _check_dpx_update,
    "buttons": _check_buttons_update,
    "satellite": _check_satellite_update,
    "companion": _check_companion_update,
}


def get_update_status(component, force=False):
    """1h TTL cache per component, same _cached() helper everything else in
    this file uses. `force=True` (the "Check Now" button) drops the cache
    entry first so the next read genuinely hits the network."""
    if force:
        with _cache_lock:
            _cache.pop(f"update_{component}", None)
    return _cached(f"update_{component}", 3600, UPDATE_CHECKS[component])


def _update_release_field(key, value):
    """Rewrite a single KEY=value line in RELEASE_FILE, adding it if
    missing. Simple full-file rewrite — this file is a handful of lines,
    no need for anything fancier."""
    try:
        lines = RELEASE_FILE.read_text().splitlines()
    except Exception:
        lines = []
    key = key.upper()
    found = False
    new_lines = []
    for line in lines:
        if line.strip().upper().startswith(f"{key}="):
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}")
    RELEASE_FILE.write_text("\n".join(new_lines) + "\n")


def _download_url(url, timeout=15):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "dpx-buttonode-ui"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception:
        return None


def _validate_python_file(data, sentinel):
    """Cheap pre-check (size + a known-stable sentinel string) followed by
    a real `python3 -m py_compile` on a temp copy — catches truncated
    downloads and syntax errors the sentinel alone wouldn't. Returns
    (ok: bool, tmp_path or None). Caller is responsible for cleaning up
    tmp_path on the success path (it gets consumed by os.replace())."""
    if not data or len(data) < 1000 or sentinel.encode() not in data:
        return False, None
    tmp_path = Path(f"/tmp/dpx-update-{os.getpid()}-{int(time.time())}.py")
    tmp_path.write_bytes(data)
    _, _, rc = run(["python3", "-m", "py_compile", str(tmp_path)])
    if rc != 0:
        tmp_path.unlink(missing_ok=True)
        return False, None
    return True, tmp_path


def _backup_and_replace(live_path, new_path):
    """Timestamped backup of the live file, then atomic swap. Keeps only
    the single most recent backup per file — no rotation system needed at
    this scale, and BOOT_STATE_FILE's crash-recovery logic (see __main__)
    only ever needs the latest one anyway."""
    ts = int(time.time())
    bak_path = live_path.with_name(live_path.name + f".bak-{ts}")
    for old in live_path.parent.glob(f"{live_path.name}.bak-*"):
        old.unlink(missing_ok=True)
    if live_path.exists():
        run(["cp", "-p", str(live_path), str(bak_path)])
    os.replace(str(new_path), str(live_path))
    os.chmod(str(live_path), 0o755)


def apply_dpx_update():
    """Downloads+validates+swaps BOTH dpx-buttonode-ui.py and
    dpx-deck-splash.py from the same release tag (they ship together),
    then restarts both services. The self-restart is last and detached —
    this process's own socket dies the moment it fires. Returns (ok, msg).
    """
    status = get_update_status("dpx")
    tag = status.get("tag")
    if not tag:
        return False, "No release tag available — check for updates first"

    base = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{tag}"
    files = [
        (f"{base}/src/dpx-buttonode-ui/dpx-buttonode-ui.py", UI_SCRIPT_PATH, "PORT = 8080"),
        (f"{base}/src/dpx-deck-splash/dpx-deck-splash.py", DECK_SPLASH_SCRIPT_PATH, "dpx-deck-splash"),
    ]
    swapped = []
    for url, live_path, sentinel in files:
        data = _download_url(url)
        ok, tmp_path = _validate_python_file(data, sentinel)
        if not ok:
            return False, f"Failed to download/validate {live_path.name} — nothing was changed" if not swapped \
                else f"Failed to download/validate {live_path.name} — {swapped[0]} was already updated, the other was not"
        _backup_and_replace(live_path, tmp_path)
        swapped.append(live_path.name)

    _update_release_field("DPX_VERSION", status["latest"])
    invalidate_build_info_cache()

    run(["systemctl", "restart", "dpx-deck-splash"])
    run(["systemd-run", "--no-block", "--quiet", "systemctl", "restart", "dpx-buttonode-ui"])
    return True, f"Updating to {status['latest']} — restarting..."


def apply_buttons_update():
    """Downloads the current buttons-deb-mirror tarball, dkpg -i's the
    .deb inside it, and restarts the Buttons service ONLY if it's
    currently the active mode — never force-switches mode. Returns
    (ok, msg)."""
    status = get_update_status("buttons")
    data = _github_get(f"/repos/{GITHUB_REPO}/releases/tags/buttons-deb-mirror")
    if not data:
        return False, "Could not reach GitHub to fetch the mirror release"
    asset_url = next(
        (a.get("browser_download_url") for a in data.get("assets", [])
         if a.get("name", "").endswith(".tar.gz")),
        None,
    )
    if not asset_url:
        return False, "No .tar.gz asset found in the mirror release"

    tar_data = _download_url(asset_url, timeout=30)
    if not tar_data:
        return False, "Failed to download the Buttons package"

    tmp_dir = Path(f"/tmp/dpx-buttons-update-{int(time.time())}")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tar_path = tmp_dir / "buttons.tar.gz"
    tar_path.write_bytes(tar_data)

    try:
        with tarfile.open(tar_path) as tf:
            tf.extractall(tmp_dir)
    except Exception as e:
        run(["rm", "-rf", str(tmp_dir)])
        return False, f"Failed to extract package: {e}"

    deb_path = next(tmp_dir.rglob("*.deb"), None)
    if not deb_path:
        run(["rm", "-rf", str(tmp_dir)])
        return False, "No .deb found inside the downloaded package"

    _, err, rc = run(["dpkg", "-i", str(deb_path)])
    if rc != 0:
        _, err2, rc2 = run(["apt-get", "install", "-f", "-y"])
        if rc2 != 0:
            run(["rm", "-rf", str(tmp_dir)])
            return False, f"Install failed: {err2 or err}"

    if get_dpx_mode() == "buttons":
        run(["systemctl", "restart", "bitfocus-buttons-usb-relay"])

    _update_release_field("BUTTONS_VERSION", status["latest"])
    invalidate_build_info_cache()
    run(["rm", "-rf", str(tmp_dir)])
    return True, f"Buttons updated to {status['latest']}"


def apply_component_update(component):
    """Kicks off the Satellite/Companion update scripts as a detached
    systemd-run job — these take 15-60 min on-device, must not block the
    HTTP request. The scripts themselves write progress/status; this just
    launches them. Returns (ok, msg) reflecting whether the LAUNCH
    succeeded, not whether the update itself will succeed."""
    script = {
        "satellite": "/usr/local/bin/update-satellite.sh",
        "companion": "/usr/local/bin/update-companion.sh",
    }.get(component)
    if not script:
        return False, "Unknown component"
    if not Path(script).exists():
        return False, f"{script} not installed on this image"
    _, err, rc = run(["systemd-run", "--no-block", "--quiet", "--unit",
                       f"dpx-update-{component}", script])
    if rc != 0:
        return False, f"Failed to launch update: {err}"
    return True, f"{component.capitalize()} update started — this can take up to an hour"


def get_component_update_progress(component):
    """Reads the status marker + tail of the log file the background
    update script writes, for the Updates tab to poll. Never raises."""
    status_file = {
        "satellite": UPDATE_SATELLITE_STATUS,
        "companion": UPDATE_COMPANION_STATUS,
    }.get(component)
    log_file = {
        "satellite": UPDATE_SATELLITE_LOG,
        "companion": UPDATE_COMPANION_LOG,
    }.get(component)
    status = "idle"
    tail = ""
    try:
        status = status_file.read_text().strip() or "idle"
    except Exception:
        pass
    try:
        lines = log_file.read_text().splitlines()
        tail = "\n".join(lines[-15:])
    except Exception:
        pass
    return {"status": status, "log_tail": tail}


def get_satellite_config():
    """Return (host, port) from /etc/dpx-satellite.conf.
    Falls back to empty host and default port 16622.
    """
    host, port = "", "16622"
    try:
        for line in SAT_CONFIG.read_text().splitlines():
            line = line.strip()
            if line.startswith("HOST="):
                host = line[5:].strip()
            elif line.startswith("PORT="):
                port = line[5:].strip()
    except Exception:
        pass
    return host, port


def write_satellite_config(host, port):
    """Persist satellite config to /etc/dpx-satellite.conf and
    stage it in /boot/satellite-config for next satellite startup.
    """
    SAT_CONFIG.write_text(f"HOST={host}\nPORT={port}\n")
    # Write satellite's one-shot boot import file
    if SAT_BOOT_CFG.parent.exists():
        content = (
            f"# Written by dpx-buttonode-ui\n"
            f"COMPANION_IP={host}\n"
            f"COMPANION_PORT={port}\n"
        )
        SAT_BOOT_CFG.write_text(content)


def render_mode(alert="", alert_cls="a-ok"):
    mode   = get_dpx_mode()
    bs     = svc_active("bitfocus-buttons-usb-relay")
    ss     = svc_active("satellite")
    cs     = svc_active("companion")
    host, port = get_satellite_config()
    has_companion = companion_installed()
    ip = get_ip()

    # Colour + label per mode
    MODE_META = {
        "buttons":   ("#2ea043", "A — Buttons USB Relay"),
        "satellite": ("#1f6feb", "B — Companion Satellite"),
        "companion": ("#9e6a03", "C — Bitfocus Companion"),
    }
    badge_color, badge_text = MODE_META.get(mode, MODE_META["buttons"])
    dash_on = dashboard_installed() and dashboard_enabled()
    if dash_on:
        badge_text += " +D"

    def mode_btn(target, label, active):
        if active:
            return f'<span style="font-size:12px;color:#8b949e;padding:8px 14px;border:1px solid #30363d;border-radius:6px;display:inline-block">{label} ✓</span>'
        disabled = "" if (target != "companion" or has_companion) else ' disabled title="Full image required"'
        return f'<button type="submit" form="mode-form-{target}" class="btn btn-p" style="font-size:12px"{disabled}>{label}</button>'

    btns = "".join([
        f'<form id="mode-form-buttons" method="POST" action="/mode" style="display:inline;margin-right:6px"><input type="hidden" name="new_mode" value="buttons">{mode_btn("buttons", "Buttons", mode=="buttons")}</form>',
        f'<form id="mode-form-satellite" method="POST" action="/mode" style="display:inline;margin-right:6px"><input type="hidden" name="new_mode" value="satellite">{mode_btn("satellite", "Satellite", mode=="satellite")}</form>',
        f'<form id="mode-form-companion" method="POST" action="/mode" style="display:inline"><input type="hidden" name="new_mode" value="companion">{mode_btn("companion", "Companion", mode=="companion")}</form>' if has_companion else
        f'<span style="font-size:12px;color:#484f58;padding:8px 14px;border:1px dashed #30363d;border-radius:6px;display:inline-block" title="Not installed — Full image required">Companion (Full only)</span>',
    ])

    companion_link = (
        f'<p class="note" style="margin-top:10px">Companion web UI: '
        f'<a href="http://{esc(ip)}:{COMPANION_PORT}" target="_blank">http://{esc(ip)}:{COMPANION_PORT}</a></p>'
        if mode == "companion" and cs else ""
    )

    bs_badge = '<span class="badge badge-on">active</span>' if bs else '<span class="badge badge-off">inactive</span>'
    ss_badge = '<span class="badge badge-on">active</span>' if ss else '<span class="badge badge-off">inactive</span>'
    cs_badge = ('<span class="badge badge-on">active</span>' if cs else '<span class="badge badge-off">inactive</span>') if has_companion else '<span class="badge badge-off">not installed</span>'

    body = f"""
<div class="sec">
  <h2>Active Mode</h2>
  <div style="background:#161b22;border:2px solid {badge_color};border-radius:10px;
              padding:18px 20px;margin-bottom:16px">
    <div style="font-size:20px;font-weight:700;color:#f0f6ff;margin-bottom:6px">{badge_text}</div>
    <div style="font-size:12px;color:#8b949e;margin-bottom:14px">/etc/dpx-mode = <code>{esc(mode)}</code></div>
    <div style="display:flex;flex-wrap:wrap;gap:8px">{btns}</div>
    {companion_link}
  </div>
</div>
<div class="sec">
  <h2>Service Status</h2>
  <div class="grid">
    <div class="card"><div class="lbl">Buttons USB Relay</div>
      <div class="val" style="font-size:13px">bitfocus-buttons-usb-relay {bs_badge}</div></div>
    <div class="card"><div class="lbl">Companion Satellite</div>
      <div class="val" style="font-size:13px">satellite {ss_badge}</div></div>
    <div class="card"><div class="lbl">Companion (Full)</div>
      <div class="val" style="font-size:13px">companion {cs_badge}</div></div>
  </div>
</div>
<div class="sec">
  <h2>Companion Server Config <span style="font-size:11px;font-weight:400;color:#8b949e">(Satellite mode)</span></h2>
  <p class="note">IP and port of your Bitfocus Companion server (TCP 16622).<br>
    Saved to <code>/etc/dpx-satellite.conf</code>. Applied on next Satellite start.</p>
  <form method="POST" action="/satellite-config">
    <table style="width:100%;border-collapse:collapse;margin-bottom:14px">
      <tr>
        <td style="padding:6px 0;color:#8b949e;font-size:13px;width:110px">Host / IP</td>
        <td><input name="host" type="text" value="{esc(host)}"
                   placeholder="192.168.1.10"
                   style="width:100%;max-width:280px;background:#161b22;border:1px solid #30363d;
                          color:#f0f6ff;border-radius:6px;padding:7px 10px;font-size:13px"></td>
      </tr>
      <tr>
        <td style="padding:6px 0;color:#8b949e;font-size:13px">Port</td>
        <td><input name="port" type="number" value="{esc(port)}"
                   placeholder="16622" min="1" max="65535"
                   style="width:120px;background:#161b22;border:1px solid #30363d;
                          color:#f0f6ff;border-radius:6px;padding:7px 10px;font-size:13px"></td>
      </tr>
    </table>
    <button type="submit" class="btn btn-p">✓ Save Config</button>
    <a href="/mode" class="btn">Cancel</a>
  </form>
</div>
{dashboard_section()}"""
    return page(body, "mode", alert, alert_cls)


def render_ssh(alert="", alert_cls="a-ok"):
    enabled = ssh_enabled()
    badge = '<span class="badge badge-on">enabled</span>' if enabled else '<span class="badge badge-off">disabled</span>'
    initial_pw_pending = get_initial_ssh_password() is not None

    # Deliberately NOT shown here — this page has no login of its own, so
    # printing the password on it would defeat the whole point of
    # generating a per-device one. It's only ever revealed by physically
    # holding the SSH key on the Stream Deck (see dpx-deck-splash.py) —
    # this box just tells you where to look, never the value itself.
    initial_pw_box = f"""
<div class="sec" style="border:2px solid #e3b341">
  <h2>⚠ Random Password Active</h2>
  <p class="note">
    A random root password was generated on first boot — it's <strong>not shown here</strong>
    (this page has no login of its own). Hold the <strong>SSH</strong> key on the Stream Deck's
    screen to reveal it, use it below to enable SSH or set your own password. It's deleted
    everywhere the moment you set a real one.
  </p>
</div>""" if initial_pw_pending else ""

    toggle_form = (
        f'<form method="POST" action="/ssh" style="display:inline">'
        f'<input type="hidden" name="action" value="{"disable" if enabled else "enable"}">'
        f'<input name="current_password" type="password" placeholder="Current root password" required '
        f'style="background:#161b22;border:1px solid #30363d;color:#f0f6ff;border-radius:6px;'
        f'padding:7px 10px;font-size:13px;margin-right:8px">'
        f'<button type="submit" class="btn {"btn-p" if not enabled else ""}">'
        f'{"Disable SSH" if enabled else "Enable SSH"}</button>'
        f'</form>'
    )

    body = f"""
{initial_pw_box}
<div class="sec">
  <h2>SSH Access</h2>
  <p class="note">Status: {badge}</p>
  <p class="note" style="margin-top:6px">
    Ships <strong>disabled by default</strong>. Every action here requires the current root
    password — this page itself has no login of its own, so that's the only thing stopping
    anyone on the LAN from flipping SSH on for themselves.
  </p>
  <div style="margin-top:14px">{toggle_form}</div>
</div>
<div class="sec">
  <h2>Change Root Password</h2>
  <form method="POST" action="/ssh">
    <input type="hidden" name="action" value="change-password">
    <table style="width:100%;border-collapse:collapse;margin-bottom:14px">
      <tr>
        <td style="padding:6px 0;color:#8b949e;font-size:13px;width:150px">Current password</td>
        <td><input name="current_password" type="password" required
                   style="width:100%;max-width:280px;background:#161b22;border:1px solid #30363d;
                          color:#f0f6ff;border-radius:6px;padding:7px 10px;font-size:13px"></td>
      </tr>
      <tr>
        <td style="padding:6px 0;color:#8b949e;font-size:13px">New password</td>
        <td><input name="new_password" type="password" minlength="8" required
                   placeholder="8+ characters"
                   style="width:100%;max-width:280px;background:#161b22;border:1px solid #30363d;
                          color:#f0f6ff;border-radius:6px;padding:7px 10px;font-size:13px"></td>
      </tr>
    </table>
    <button type="submit" class="btn btn-p">Change Password</button>
  </form>
</div>"""
    return page(body, "ssh", alert, alert_cls)


def _update_card(title, status, apply_action, in_flight=False):
    current = esc(status.get("current", "unknown"))
    latest  = esc(status.get("latest", "unknown"))
    available = status.get("available", False)
    badge = (
        '<span class="badge badge-on">update available</span>' if available
        else '<span class="badge badge-off">up to date</span>'
    )
    btn = ""
    if in_flight:
        btn = '<span class="badge badge-off">updating…</span>'
    elif available:
        btn = (
            f'<form method="POST" action="/updates" style="display:inline">'
            f'<input type="hidden" name="action" value="{apply_action}">'
            f'<button type="submit" class="btn btn-p">Update to {latest}</button>'
            f'</form>'
        )
    return f"""
<div class="sec">
  <h2>{esc(title)}</h2>
  <p class="note">Status: {badge}</p>
  <p class="note">Current: <code>{current}</code> &nbsp;&middot;&nbsp; Latest: <code>{latest}</code></p>
  <div style="margin-top:10px">{btn}</div>
</div>"""


def render_updates(alert="", alert_cls="a-ok"):
    dpx    = get_update_status("dpx")
    btns   = get_update_status("buttons")
    sat    = get_update_status("satellite")
    bld    = get_build_info()
    has_companion = bld.get("variant") == "full"
    comp   = get_update_status("companion") if has_companion else None

    sat_prog  = get_component_update_progress("satellite")
    comp_prog = get_component_update_progress("companion") if has_companion else {"status": "idle"}
    sat_running  = sat_prog.get("status") == "running"
    comp_running = comp_prog.get("status") == "running"

    refresh = '<meta http-equiv="refresh" content="15">' if (sat_running or comp_running) else ""
    warn_box = ""
    if sat_running or comp_running:
        warn_box = (
            '<div class="sec" style="border:2px solid #e3b341">'
            '<h2>⚠ Update In Progress</h2>'
            '<p class="note">This can take up to an hour. Do not power off the device. '
            'This page refreshes itself every 15s.</p>'
            + (f'<pre style="white-space:pre-wrap;font-size:11px;color:#8b949e">{esc(sat_prog.get("log_tail",""))}</pre>' if sat_running else "")
            + (f'<pre style="white-space:pre-wrap;font-size:11px;color:#8b949e">{esc(comp_prog.get("log_tail",""))}</pre>' if comp_running else "")
            + '</div>'
        )

    check_form = (
        '<form method="POST" action="/updates" style="display:inline">'
        '<input type="hidden" name="action" value="check">'
        '<button type="submit" class="btn">Check Now</button>'
        '</form>'
    )

    body = f"""
{refresh}
<div class="sec">
  <h2>Software Updates</h2>
  <p class="note">Checked against GitHub Releases, cached for up to an hour. Nothing installs itself — every update is a button push here.</p>
  <div style="margin-top:10px">{check_form}</div>
</div>
{warn_box}
{_update_card("dpx-buttonode (web UI + deck splash)", dpx, "apply-dpx")}
{_update_card("Bitfocus Buttons USB Relay", btns, "apply-buttons")}
{_update_card("Companion Satellite", sat, "apply-satellite", in_flight=sat_running)}
{_update_card("Bitfocus Companion (full)", comp, "apply-companion", in_flight=comp_running) if has_companion else ""}
"""
    return page(body, "updates", alert, alert_cls)


# ── Request handler ────────────────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # suppress per-request noise in journal

    def html(self, body, code=200):
        b = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(b)

    def redir(self, loc):
        self.send_response(303)
        self.send_header("Location", loc)
        self.end_headers()

    def read_post(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n).decode("utf-8", errors="replace")
        params = urllib.parse.parse_qs(raw, keep_blank_values=True)
        return {k: v[0].strip() for k, v in params.items()}

    # ── GET ────────────────────────────────────────────────────────────────

    def do_GET(self):
        path = self.path.split("?")[0]
        qs   = dict(urllib.parse.parse_qsl(self.path.partition("?")[2]))

        # Resolve alert from redirect query string
        alert, alert_cls = "", "a-ok"
        ok_msgs = {
            "hostname":   "✓ Hostname updated — mDNS will reflect the change within a few seconds",
            "restart":    "✓ Buttons service restarted",
            "powercycle": "✓ USB power cycled — deck went dark and is reconnecting",
        }
        err_msgs = {
            "api":     "✗ Buttons API did not respond — is bitfocus-buttons-usb-relay running?",
            "invalid": "✗ Invalid input",
        }
        if "ok" in qs:
            if qs["ok"] == "net-dhcp":
                alert = "✓ Switched to DHCP — IP will be assigned by your router. Buttons service restarted."
            elif qs["ok"] == "net-static":
                ip  = esc(qs.get("ip", "unknown"))
                gw  = esc(qs.get("gw", "unknown"))
                alert = f"✓ Static IP applied: <code>{ip}</code> via <code>{gw}</code> — Buttons service restarted."
            else:
                alert = ok_msgs.get(qs["ok"], "✓ Done")
        elif "err" in qs:
            alert     = err_msgs.get(qs["err"], "✗ An error occurred")
            alert_cls = "a-err"

        if path == "/":
            self.html(render_status(alert, alert_cls))
        elif path == "/hostname":
            self.html(render_hostname(alert=alert, alert_cls=alert_cls))
        elif path == "/network":
            self.html(render_network(alert, alert_cls))
        elif path == "/devices":
            self.html(render_devices(alert, alert_cls))
        elif path == "/nodes":
            self.html(render_nodes(alert, alert_cls))
        elif path == "/mode":
            self.html(render_mode(alert, alert_cls))
        elif path == "/ssh":
            self.html(render_ssh(alert, alert_cls))
        elif path == "/updates":
            self.html(render_updates(alert, alert_cls))
        elif path in ("/favicon.png", "/favicon.ico"):
            favicon = Path("/usr/local/bin/fav_icon.png")
            if favicon.exists():
                data = favicon.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "max-age=86400")
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404); self.end_headers()
        else:
            self.html("<html><body><h1>Not found</h1></body></html>", 404)

    # ── POST ───────────────────────────────────────────────────────────────

    def do_POST(self):
        params = self.read_post()
        path   = self.path.split("?")[0]

        # ── /hostname ──────────────────────────────────────────────────────
        if path == "/hostname":
            name = params.get("hostname", "")
            if not validate_hostname(name):
                self.html(render_hostname(
                    val=name,
                    alert="✗ Invalid hostname — use letters, numbers, and hyphens only",
                    alert_cls="a-err",
                ))
                return

            _, err, rc = run(["hostnamectl", "set-hostname", "--static", name])
            if rc != 0:
                self.html(render_hostname(
                    val=name,
                    alert=f"✗ hostnamectl failed: {esc(err)}",
                    alert_cls="a-err",
                ))
                return

            # Write /etc/hostname explicitly for belt-and-suspenders
            Path("/etc/hostname").write_text(name + "\n")

            # Update 127.0.1.1 line in /etc/hosts
            hosts = Path("/etc/hosts").read_text()
            hosts = re.sub(
                r"^127\.0\.1\.1\s+\S+",
                f"127.0.1.1\t{name}",
                hosts,
                flags=re.MULTILINE,
            )
            if "127.0.1.1" not in hosts:
                hosts += f"\n127.0.1.1\t{name}\n"
            Path("/etc/hosts").write_text(hosts)

            # Prevent dpx-set-hostname.service from overwriting on next boot
            Path(HOSTNAME_MARKER).touch()

            # Tell avahi about the new name
            run(["systemctl", "reload-or-restart", "avahi-daemon"])

            self.redir("/?ok=hostname")

        # ── /network ───────────────────────────────────────────────────────
        elif path == "/network":
            net  = get_net_info()
            mode = params.get("mode", "dhcp")

            if net["networkd"]:
                iface   = net.get("iface", get_primary_iface())
                mode    = params.get("mode", "dhcp")
                ip_cidr = params.get("ip", "") if mode == "static" else None
                gw      = params.get("gateway", "") if mode == "static" else None
                dns     = params.get("dns", "8.8.8.8") if mode == "static" else None

                if mode == "static" and (not validate_ip((ip_cidr or "").split("/")[0]) or not validate_ip(gw or "")):
                    self.html(render_network("✗ Invalid IP address or gateway", "a-err"))
                    return

                # Determine redirect target AFTER the change
                # Always use .local (mDNS) — avahi updates quickly and avoids
                # ARP propagation delay when the IP itself changes.
                hostname = get_hostname()
                base_url = f"http://{hostname}.local:{PORT}"
                if mode == "dhcp":
                    redirect = f"{base_url}/network?ok=net-dhcp"
                    msg     = "Switching to DHCP \u2014 your router will assign an IP."
                else:
                    redirect = f"{base_url}/network?ok=net-static&ip={urllib.parse.quote(ip_cidr)}&gw={urllib.parse.quote(gw)}"
                    msg     = f"Setting static IP to <code>{esc(ip_cidr)}</code> via <code>{esc(gw)}</code>."

                # Send the 'applying' page BEFORE making the disruptive change.
                # The meta-refresh carries the browser to the new address once networkd is done.
                applying_html = page(f"""
<div class="sec"><h2>Applying Network Changes…</h2>
  <p class="note" style="margin-bottom:10px">{msg}</p>
  <p class="note">Redirecting in 8 seconds \u2014 if it doesn't load,
    go to <a href="{redirect}">{redirect}</a></p>
</div>
<meta http-equiv="refresh" content="8;url={redirect}">""", "network")
                b = applying_html.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
                self.wfile.flush()

                # Run the apply in a background thread so the HTTP connection
                # closes cleanly BEFORE netplan changes the IP (which would
                # otherwise kill the socket and crash the server process).
                _iface, _mode, _ip, _gw, _dns = iface, mode, ip_cidr, gw, dns
                def _apply():
                    import sys
                    time.sleep(1)
                    print(f"dpx-buttonode-ui: apply start mode={_mode} iface={_iface} ip={_ip} gw={_gw}", file=sys.stderr, flush=True)
                    try:
                        write_networkd_config(_iface, _mode, _ip, _gw, _dns)
                        print(f"dpx-buttonode-ui: apply done", file=sys.stderr, flush=True)
                    except Exception as exc:
                        print(f"dpx-buttonode-ui: apply error: {exc}", file=sys.stderr, flush=True)
                threading.Thread(target=_apply, daemon=True).start()
                return

            # nmcli path
            out, _, _ = run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", "--active"])
            conn = ""
            for line in out.splitlines():
                parts = line.split(":")
                if len(parts) >= 2 and "ethernet" in parts[1].lower():
                    conn = parts[0]
                    break

            if not conn:
                self.html(render_network(
                    alert="✗ No active Ethernet connection found — is the cable plugged in?",
                    alert_cls="a-err",
                ))
                return

            if mode == "dhcp":
                run(["nmcli", "connection", "modify", conn,
                     "ipv4.method", "auto",
                     "ipv4.addresses", "",
                     "ipv4.gateway",  "",
                     "ipv4.dns",      ""])
            elif mode == "static":
                ip_cidr = params.get("ip", "")
                gw      = params.get("gateway", "")
                dns     = params.get("dns", "8.8.8.8")
                ip_only = ip_cidr.split("/")[0]
                if not validate_ip(ip_only) or not validate_ip(gw):
                    self.html(render_network(
                        alert="✗ Invalid IP address or gateway",
                        alert_cls="a-err",
                    ))
                    return
                run(["nmcli", "connection", "modify", conn,
                     "ipv4.method",    "manual",
                     "ipv4.addresses", ip_cidr,
                     "ipv4.gateway",   gw,
                     "ipv4.dns",       dns])
            else:
                self.redir("/?err=invalid")
                return

            run(["nmcli", "connection", "up", conn])
            run(["systemctl", "restart", "bitfocus-buttons-usb-relay"])
            if mode == "dhcp":
                self.redir("/network?ok=net-dhcp")
            else:
                ip_cidr = params.get("ip", "")
                gw      = params.get("gateway", "")
                self.redir(f"/network?ok=net-static&ip={urllib.parse.quote(ip_cidr)}&gw={urllib.parse.quote(gw)}")

        # ── /power-cycle-deck ──────────────────────────────────────────
        elif path == "/power-cycle-deck":
            deck = find_streamdeck_usb_path()
            if not deck:
                self.html(render_devices(alert="✗ No Stream Deck found on USB", alert_cls="a-err"))
                return
            ok, err = usb_power_cycle(deck)
            if not ok:
                self.html(render_devices(alert=f"✗ USB power cycle failed: {esc(err)}", alert_cls="a-err"))
                return
            self.redir("/devices?ok=powercycle")

        # ── /restart-buttons ───────────────────────────────────────────────
        elif path == "/restart-buttons":
            _, err, rc = run(["systemctl", "restart", "bitfocus-buttons-usb-relay"])
            if rc != 0:
                self.html(render_devices(alert=f"✗ restart failed: {esc(err)}", alert_cls="a-err"))
                return
            self.redir("/devices?ok=restart")

        # ── /dashboard ───────────────────────────────────────────────────────
        elif path == "/dashboard":
            if not dashboard_installed():
                self.html(render_mode(alert="✗ Dashboard is not installed on this image", alert_cls="a-err"))
                return
            action = params.get("action", "")
            set_dashboard_enabled(action == "enable")
            self.redir("/mode?ok=dashboard")

        # ── /dashboard/fullscreen ───────────────────────────────────────
        elif path == "/dashboard/fullscreen":
            if not dashboard_enabled():
                self.html(render_mode(alert="✗ Dashboard isn't running", alert_cls="a-err"))
                return
            ok, msg = dashboard_toggle_fullscreen()
            if ok:
                self.redir("/mode?ok=fullscreen")
            else:
                self.html(render_mode(alert=f"✗ F11 send failed: {esc(msg)}", alert_cls="a-err"))

        # ── /mode ────────────────────────────────────────────────────────
        elif path == "/mode":
            new_mode = params.get("new_mode", "").strip()
            ok, msg = switch_mode(new_mode)
            self.html(render_mode(
                alert=("✓ " if ok else "✗ ") + esc(msg),
                alert_cls="a-ok" if ok else "a-err",
            ))

        # ── /satellite-config ──────────────────────────────────────────
        elif path == "/satellite-config":
            host = params.get("host", "").strip()
            port = params.get("port", "16622").strip()
            if not re.match(r"^\d+$", port) or not (1 <= int(port) <= 65535):
                self.html(render_mode(alert="✗ Port must be a number between 1 and 65535", alert_cls="a-err"))
                return
            write_satellite_config(host, port)
            # If satellite is currently running, push config via API and restart
            if svc_active("satellite"):
                try:
                    body = f'{{"host": "{host}", "port": {int(port)}}}'
                    req = urllib.request.Request(
                        f"{SATELLITE_API}/api/config",
                        data=body.encode(),
                        method="POST",
                        headers={"Content-Type": "application/json"},
                    )
                    urllib.request.urlopen(req, timeout=3)
                except Exception:
                    pass  # best-effort; config is also staged for next start
                run(["systemctl", "restart", "satellite"])
            self.html(render_mode(alert="✓ Satellite config saved", alert_cls="a-ok"))

        # ── /ssh ────────────────────────────────────────────────────────
        elif path == "/ssh":
            action = params.get("action", "")
            current_password = params.get("current_password", "")
            if not verify_root_password(current_password):
                self.html(render_ssh(alert="✗ Incorrect current password", alert_cls="a-err"))
                return
            if action == "enable":
                set_ssh_enabled(True)
                self.html(render_ssh(alert="✓ SSH enabled", alert_cls="a-ok"))
            elif action == "disable":
                set_ssh_enabled(False)
                self.html(render_ssh(alert="✓ SSH disabled", alert_cls="a-ok"))
            elif action == "change-password":
                ok, msg = change_root_password(params.get("new_password", ""))
                self.html(render_ssh(alert=("✓ " if ok else "✗ ") + esc(msg), alert_cls="a-ok" if ok else "a-err"))
            else:
                self.html(render_ssh(alert="✗ Invalid action", alert_cls="a-err"))

        # ── /updates ────────────────────────────────────────────────────
        elif path == "/updates":
            action = params.get("action", "")
            if action == "check":
                for component in UPDATE_CHECKS:
                    if component == "companion" and get_build_info().get("variant") != "full":
                        continue
                    get_update_status(component, force=True)
                self.html(render_updates(alert="✓ Checked for updates", alert_cls="a-ok"))
            elif action == "apply-dpx":
                ok, msg = apply_dpx_update()
                self.html(render_updates(alert=("✓ " if ok else "✗ ") + esc(msg), alert_cls="a-ok" if ok else "a-err"))
            elif action == "apply-buttons":
                ok, msg = apply_buttons_update()
                self.html(render_updates(alert=("✓ " if ok else "✗ ") + esc(msg), alert_cls="a-ok" if ok else "a-err"))
            elif action == "apply-satellite":
                ok, msg = apply_component_update("satellite")
                self.html(render_updates(alert=("✓ " if ok else "✗ ") + esc(msg), alert_cls="a-ok" if ok else "a-err"))
            elif action == "apply-companion":
                ok, msg = apply_component_update("companion")
                self.html(render_updates(alert=("✓ " if ok else "✗ ") + esc(msg), alert_cls="a-ok" if ok else "a-err"))
            else:
                self.html(render_updates(alert="✗ Invalid action", alert_cls="a-err"))

        else:
            self.html("<html><body><h1>Not found</h1></body></html>", 404)


# ── Main ───────────────────────────────────────────────────────────────────────
#
# --apply-mode <buttons|satellite|companion>, --toggle-net, and
# --pin-static <ip> are internal CLI subcommands, not part of the web UI.
# They exist so a privileged, narrowly-scoped caller (see
# /etc/sudoers.d/dpx-splash) can trigger the exact same mode-switch /
# network logic the web UI uses, without duplicating it or running with
# broad privilege itself. Used by the deck splash service's keypress
# handlers — the deck does its own select/cycle UI locally (short press
# advances a not-yet-committed candidate, long press commits) and only
# calls in here with the final chosen value.
#
# --apply-mode's sudoers rule whitelists exactly the three valid mode
# values as three separate fixed command lines — no wildcard, nothing to
# validate beyond an exact string match. --pin-static can't be enumerated
# that way (any of ~4 billion IPs), so its sudoers rule is a loose glob
# instead — pin_static()'s own validate_ip() call is the real gate there,
# not sudoers. switch_mode() rejects anything invalid the same way.

if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--apply-mode":
        ok, msg = switch_mode(sys.argv[2])
        print(msg)
        sys.exit(0 if ok else 1)
    if len(sys.argv) >= 2 and sys.argv[1] == "--toggle-net":
        ok, msg = toggle_net()
        print(msg)
        sys.exit(0 if ok else 1)
    if len(sys.argv) >= 3 and sys.argv[1] == "--pin-static":
        ok, msg = pin_static(sys.argv[2])
        print(msg)
        sys.exit(0 if ok else 1)
    if len(sys.argv) >= 2 and sys.argv[1] == "--toggle-dashboard":
        if not dashboard_installed():
            print("Dashboard is not installed on this image")
            sys.exit(1)
        new_state = not dashboard_enabled()
        set_dashboard_enabled(new_state)
        print("Dashboard enabled" if new_state else "Dashboard disabled")
        sys.exit(0)

    # Crash-recovery: a self-update that compiles fine but throws before
    # the server ever binds would otherwise restart-loop forever under
    # systemd's Restart=on-failure with no way to recover short of SSH/
    # physical access. Track boot attempts in a small window; too many too
    # fast means the currently-live file is bad, so restore the last known-
    # good backup (written by _backup_and_replace() during apply_dpx_update)
    # and let systemd's next restart come up on that instead.
    CRASH_WINDOW_SECONDS = 60
    CRASH_THRESHOLD = 3
    try:
        attempts = json.loads(BOOT_STATE_FILE.read_text())
        if not isinstance(attempts, list):
            attempts = []
    except Exception:
        attempts = []
    now = time.time()
    attempts = [t for t in attempts if now - t < CRASH_WINDOW_SECONDS]
    attempts.append(now)
    try:
        BOOT_STATE_FILE.write_text(json.dumps(attempts))
    except Exception:
        pass
    if len(attempts) > CRASH_THRESHOLD:
        backups = sorted(UI_SCRIPT_PATH.parent.glob(f"{UI_SCRIPT_PATH.name}.bak-*"))
        if backups:
            print(f"dpx-buttonode-ui: {len(attempts)} boot attempts in "
                  f"{CRASH_WINDOW_SECONDS}s — restoring {backups[-1].name}")
            os.replace(str(backups[-1]), str(UI_SCRIPT_PATH))
            os.chmod(str(UI_SCRIPT_PATH), 0o755)
            try:
                BOOT_STATE_FILE.unlink()
            except Exception:
                pass
            sys.exit(1)

    server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"dpx-buttonode-ui listening on :{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
