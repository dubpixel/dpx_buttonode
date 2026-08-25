#!/usr/bin/env bash
# dpx-init-ssh.sh
# Generates a random root password on first boot and writes it where the
# web UI (root-only, /etc) and the deck splash (buttons-group-readable,
# /etc/dpx-buttonode-release-adjacent) can both show it. SSH itself stays
# disabled (see dpx-buttonode.pkr.hcl) — this only replaces the login
# credential a future "Enable SSH" action would otherwise be gated behind.
#
# Why this exists: shipping every image with the same hardcoded root
# password (the old default, "1234") meant anyone who'd read this repo's
# own README knew every unit's login. A per-device random password
# generated at first boot has nothing to look up — you have to actually
# be able to see the device (its Stream Deck, or its web UI on the LAN)
# to learn it. The web UI's SSH tab clears this file the moment the user
# sets their own password, so it's a one-time, self-expiring credential.
#
# Installed at: /usr/local/bin/dpx-init-ssh.sh
# Managed by:   dpx-init-ssh.service (oneshot, runs once — see MARKER)

set -euo pipefail

MARKER="/var/lib/dpx-ssh-initialized"
PASS_FILE="/etc/dpx-initial-ssh-password"

# Already generated — exit fast so subsequent boots are instant, and so
# we never overwrite a password the user may already be relying on.
[ -f "$MARKER" ] && exit 0

# 10 chars from an unambiguous alnum set (no 0/O/1/l/I) — short enough to
# read off a Stream Deck key, long enough to not be trivially guessable
# for the "keep honest people honest" bar this is aiming for, not
# resistance to a targeted attacker with LAN access and time.
PASS=$(tr -dc 'A-HJ-NP-Za-km-z2-9' < /dev/urandom | head -c 10)

echo "root:${PASS}" | chpasswd

# root-owned, but group-readable by `buttons` — the same group dpx-splash
# (the deck splash service's low-priv user) is already in for HID access,
# so it can show this password without any new privilege grant.
echo "$PASS" > "$PASS_FILE"
chown root:buttons "$PASS_FILE"
chmod 0640 "$PASS_FILE"

touch "$MARKER"
echo "dpx-init-ssh: initial root password generated"
