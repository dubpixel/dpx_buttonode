#!/usr/bin/env bash
# dpx-init-ssh.sh
# Generates a random root password on first boot and writes it group-
# readable by `buttons` so dpx-deck-splash (already in that group for HID
# access) can hold-to-reveal it on the deck's SSH key. SSH itself stays
# disabled (see dpx-buttonode.pkr.hcl) — this only replaces the login
# credential a future "Enable SSH" action would otherwise be gated behind.
#
# Why this exists: shipping every image with the same hardcoded root
# password (the old default, "1234") meant anyone who'd read this repo's
# own README knew every unit's login. A per-device random password
# generated at first boot has nothing to look up. Deliberately NOT shown
# anywhere on the web UI (which has no login of its own, reachable by
# anyone on the LAN) — the deck's hold-to-reveal SSH key is the only
# place it's ever displayed, so learning it requires physical access to
# the device. dpx-buttonode-ui.py's SSH tab deletes this file the moment
# the user sets their own password, so it's a one-time, self-expiring
# credential.
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
#
# `head -c 10` closing early once it has enough bytes sends SIGPIPE back
# up the pipe — with `set -o pipefail` that makes the whole pipeline exit
# non-zero even though it produced exactly what we wanted (confirmed on
# hardware: this killed the script under -e every time). Reading a fixed,
# bounded chunk from /dev/urandom first and filtering it with `cut`
# (which always reads to EOF, never closes early) avoids the SIGPIPE
# entirely. 512 input bytes filtered through this ~58/256-char set
# reliably yields well over 10 usable characters.
# LC_ALL=C matters too: raw random bytes aren't valid UTF-8, and `tr` in
# a UTF-8 locale can fail outright ("illegal byte sequence") trying to
# multibyte-decode them — C locale makes it operate byte-for-byte instead.
PASS=$(LC_ALL=C head -c 512 /dev/urandom | LC_ALL=C tr -dc 'A-HJ-NP-Za-km-z2-9' | cut -c1-10)

echo "root:${PASS}" | chpasswd

# root-owned, but group-readable by `buttons` — the same group dpx-splash
# (the deck splash service's low-priv user) is already in for HID access,
# so it can show this password without any new privilege grant.
echo "$PASS" > "$PASS_FILE"
chown root:buttons "$PASS_FILE"
chmod 0640 "$PASS_FILE"

touch "$MARKER"
echo "dpx-init-ssh: initial root password generated"
