#!/usr/bin/env python3
"""
dpx-buttnode-ui — DPX device configuration web interface
Installed: /usr/local/bin/dpx-buttnode-ui.py
Service:   dpx-buttnode-ui.service
Port:      8080

Zero external dependencies — uses Python 3 stdlib only.
"""

import http.server
import os
import re
import socket
import subprocess
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
SAT_CONFIG     = Path("/etc/dpx-satellite.conf")    # our persistent satellite config
SAT_BOOT_CFG   = Path("/boot/satellite-config")     # satellite's one-shot import file
SATELLITE_API  = "http://localhost:9999"             # satellite REST API
COMPANION_DIR  = Path("/opt/companion")              # present on full images only
COMPANION_PORT = 8000                                # companion web UI port

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
    # Reconnect Buttons
    run(["systemctl", "restart", "bitfocus-buttons-usb-relay"])
    # Restart ourselves — the server socket breaks when the IP changes.
    # Use systemd-run so this continues after our process exits.
    run(["systemd-run", "--no-block", "--quiet",
         "systemctl", "restart", "dpx-buttnode-ui"])


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


def usb_power_cycle(port_path, delay=2):
    """Unbind then rebind a USB port. Deck goes dark for `delay` seconds."""
    unbind = Path("/sys/bus/usb/drivers/usb/unbind")
    bind   = Path("/sys/bus/usb/drivers/usb/bind")
    try:
        unbind.write_text(port_path)
        time.sleep(delay)
        bind.write_text(port_path)
        return True, ""
    except Exception as e:
        return False, str(e)


def discover_buttnodes():
    return _cached("buttnodes", 10, _discover_buttnodes_raw)

def _discover_buttnodes_raw():
    """Return list of dpx-buttnode instances found via avahi-browse.
    Requires avahi-daemon running and the _dpx-buttnode._tcp service registered.
    Each entry: {hostname, addr, port, is_self}
    """
    # -p parseable, -t terminate when done, -r resolve addresses
    out, _, rc = run(["avahi-browse", "-p", "-t", "-r", "_dpx-buttnode._tcp"])
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
        f'dpx-buttnode v{esc(bld["dpx_version"])} [{esc(variant_tag)}]'
        f' &nbsp;&middot;&nbsp; buttons {esc(bld["buttons_version"])}'
        f' &nbsp;&middot;&nbsp; satellite {esc(bld["satellite_version"])}'
        f'{companion_part}'
        f' &nbsp;&middot;&nbsp; {esc(bld["git_branch"])}@{esc(bld["git_commit"])}'
        f' &nbsp;&middot;&nbsp; built {esc(bld["build_date"])}'
        f'</div>'
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{hostname} — dpx-buttnode-ui</title>
<link rel="icon" type="image/png" href="/favicon.png">
<style>{CSS}</style>
</head>
<body>
<div class="hdr"><h1>⯁ {hostname}</h1><span class="tag">dpx-buttnode-ui</span></div>
<nav class="nav">{nav}</nav>
<div class="wrap">{al}{content}</div>
{footer}
</body>
</html>"""


# ── Page renderers ─────────────────────────────────────────────────────────────

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

    mode_color = {"buttons": "#3fb950", "satellite": "#58a6ff", "companion": "#e3b341"}.get(mode, "#3fb950")
    mode_card = f"""  <div class="card"><div class="lbl">Mode</div>
    <div class="val" style="font-size:16px;font-weight:700;color:{mode_color}">{mode.upper()}</div>
    {svc_label}
    {mode_detail}</div>"""

    grid = f"""
<div class="grid">
  <div class="card" style="grid-column:span 2"><div class="lbl">Hostname</div>
    <div class="val" style="font-size:15px">{host}</div></div>
  <div class="card"><div class="lbl">IP Address</div>
    <div class="val">{ip}</div></div>
  <div class="card"><div class="lbl">MAC</div>
    <div class="val" style="font-size:12px">{mac}</div></div>
  <div class="card"><div class="lbl">Network</div>
    <div class="val" style="font-size:14px">{esc(net['mode']).upper()}</div></div>
{mode_card}
  <div class="card"><div class="lbl">mDNS</div>
    <div class="val {'on' if av else 'off'}">{'active' if av else 'inactive'}</div></div>
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
             placeholder="dpx-buttnode-XXXX"
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


def render_nodes(alert="", alert_cls="a-ok"):
    nodes = discover_buttnodes()
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
        rows = '<p class="note">No dpx-buttnodes found on this network.<br>Make sure avahi-daemon is running on all units.</p>'

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


RELEASE_FILE = Path("/etc/dpx-buttnode-release")

def get_build_info():
    return _cached("build_info", 3600, _get_build_info_raw)

def _get_build_info_raw():
    """Return dict of build metadata from /etc/dpx-buttnode-release.
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
            f"# Written by dpx-buttnode-ui\n"
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
</div>"""
    return page(body, "mode", alert, alert_cls)


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
                    print(f"dpx-buttnode-ui: apply start mode={_mode} iface={_iface} ip={_ip} gw={_gw}", file=sys.stderr, flush=True)
                    try:
                        write_networkd_config(_iface, _mode, _ip, _gw, _dns)
                        print(f"dpx-buttnode-ui: apply done", file=sys.stderr, flush=True)
                    except Exception as exc:
                        print(f"dpx-buttnode-ui: apply error: {exc}", file=sys.stderr, flush=True)
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
        # ── /mode ────────────────────────────────────────────────────────
        elif path == "/mode":
            new_mode = params.get("new_mode", "").strip()
            valid = {"buttons", "satellite", "companion"}
            if new_mode not in valid:
                self.html(render_mode(alert="✗ Invalid mode", alert_cls="a-err"))
                return
            if new_mode == "companion" and not companion_installed():
                self.html(render_mode(alert="✗ Full Companion not installed — flash the Full image variant", alert_cls="a-err"))
                return
            current = get_dpx_mode()
            if new_mode == current:
                self.redir("/mode")
                return
            SVC_MAP = {
                "buttons":   "bitfocus-buttons-usb-relay",
                "satellite": "satellite",
                "companion": "companion",
            }
            old_svc = SVC_MAP.get(current, "bitfocus-buttons-usb-relay")
            new_svc = SVC_MAP[new_mode]
            # If switching TO satellite, stage the config before starting
            if new_mode == "satellite":
                host, port = get_satellite_config()
                if host:
                    write_satellite_config(host, port)
            run(["systemctl", "stop",    old_svc])
            run(["systemctl", "disable", old_svc])
            run(["systemctl", "enable",  new_svc])
            _, err, rc = run(["systemctl", "start", new_svc])
            if rc != 0:
                self.html(render_mode(
                    alert=f"✗ Failed to start {esc(new_svc)}: {esc(err)}",
                    alert_cls="a-err",
                ))
                return
            MODE_FILE.write_text(new_mode + "\n")
            LABELS = {"buttons": "Buttons USB Relay", "satellite": "Companion Satellite", "companion": "Bitfocus Companion"}
            self.html(render_mode(
                alert=f"✓ Switched to {LABELS[new_mode]}",
                alert_cls="a-ok",
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
                        headers={{"Content-Type": "application/json"}},
                    )
                    urllib.request.urlopen(req, timeout=3)
                except Exception:
                    pass  # best-effort; config is also staged for next start
                run(["systemctl", "restart", "satellite"])
            self.html(render_mode(alert="✓ Satellite config saved", alert_cls="a-ok"))
        else:
            self.html("<html><body><h1>Not found</h1></body></html>", 404)


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"dpx-buttnode-ui listening on :{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
