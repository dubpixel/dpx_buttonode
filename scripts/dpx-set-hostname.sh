#!/usr/bin/env bash
# dpx-set-hostname.sh
# Sets this device's hostname to dpx-buttonode-XXXX where XXXX is the last
# 4 hex characters (uppercase) of the primary Ethernet MAC address.
#
# Installed at: /usr/local/bin/dpx-set-hostname.sh
# Managed by:   dpx-set-hostname.service (oneshot, runs before avahi/network)
#
# Why sysfs instead of `ip link show`:
#   /sys/class/net is populated by the kernel driver at module load time —
#   before any network stack (NetworkManager, systemd-networkd, avahi) starts.
#   Reading it here is guaranteed to work at boot, no timing dependency.

set -euo pipefail

MARKER="/var/lib/dpx-hostname-set"

# Already configured — exit fast so subsequent boots are instant
[ -f "$MARKER" ] && exit 0

# ── Find the first real Ethernet interface ─────────────────────────────────
# /sys/class/net/<iface>/type == "1" means ARPHRD_ETHER (real Ethernet).
# This excludes: lo (772), wifi (803), veth/tun/tap, bridges, etc.
MAC=""
IFACE_USED=""

for addr_path in /sys/class/net/*/address; do
    iface=$(basename "$(dirname "$addr_path")")
    type_path="/sys/class/net/${iface}/type"

    # Must have a type file and must be ARPHRD_ETHER (1)
    [ -f "$type_path" ]                  || continue
    [ "$(cat "$type_path")" = "1" ]      || continue

    addr=$(cat "$addr_path" 2>/dev/null) || continue

    # Validate MAC format: xx:xx:xx:xx:xx:xx (lowercase hex from sysfs)
    [[ "$addr" =~ ^[0-9a-f]{2}(:[0-9a-f]{2}){5}$ ]] || continue

    # Skip all-zeros (unconfigured / driver placeholder)
    [[ "$addr" == "00:00:00:00:00:00" ]] && continue

    MAC="$addr"
    IFACE_USED="$iface"
    break
done

if [ -z "$MAC" ]; then
    echo "dpx-set-hostname: no real Ethernet interface found — keeping default hostname"
    touch "$MARKER"
    exit 0
fi

# ── Derive suffix ──────────────────────────────────────────────────────────
# Strip colons, take last 4 hex chars (last 2 MAC octets), uppercase.
# e.g. aa:bb:cc:dd:ee:ff → EEFF
SUFFIX=$(echo "$MAC" | tr -d ':' | rev | cut -c1-4 | rev | tr '[:lower:]' '[:upper:]')
NEW_HOSTNAME="dpx-buttonode-${SUFFIX}"

echo "dpx-set-hostname: iface=${IFACE_USED}  MAC=${MAC}  →  ${NEW_HOSTNAME}"

# ── Apply ──────────────────────────────────────────────────────────────────
hostnamectl set-hostname --static "$NEW_HOSTNAME"

# Ensure /etc/hostname is in sync (hostnamectl writes it, but be explicit)
echo "$NEW_HOSTNAME" > /etc/hostname

# Update the 127.0.1.1 FQDN line in /etc/hosts
if grep -q "^127\.0\.1\.1" /etc/hosts; then
    sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t${NEW_HOSTNAME}/" /etc/hosts
else
    printf "127.0.1.1\t%s\n" "$NEW_HOSTNAME" >> /etc/hosts
fi

# Mark done — avahi and subsequent services see the new hostname on start
touch "$MARKER"
echo "dpx-set-hostname: done"
