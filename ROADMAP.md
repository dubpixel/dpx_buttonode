# dpx-buttonode Roadmap

Loose collection of planned improvements and ideas. Not a commitment, not a schedule — just a living list.

---

## Discovery & Setup UX

### `/label` — Self-Printed QR Label Page
**Status:** planned — `- [ ]`

Each buttonode already knows its own hostname (`dpx-buttonode-XXXX.local`) at runtime via Avahi/mDNS. The problem is you can't pre-print a label before first boot because the hostname is MAC-derived.

**Solution:** Add a `/label` route to `dpx-buttonode-ui.py` that renders a clean printable page containing:
- A QR code pointing to `http://dpx-buttonode-XXXX.local:8080`
- The `.local` URL printed in large text below it
- A print button (hides chrome, triggers `window.print()`)

Workflow: boot the unit → open its IP in a browser → go to `/label` → print → stick on box.

No external libraries needed. A pure-JS QR generator (e.g. `qrcode.js` inlined) handles the QR client-side.

---

### Stream Deck HID Boot Splash
**Status:** hardware-validated end to end (Phase 1: 2026-08-24; Phase 2/3: 2026-08-28/29, Stream Deck MK.2 + Original 15-key) `- [x]` Phase 1 / `- [x]` Phase 2/3 code / `- [x]` Phase 2/3 hardware test

Draw device status directly onto the attached Stream Deck's keys via HID, instead of requiring SSH or the
web UI to find a fresh unit on the network.

- **Phase 1** (hardware-validated): read-only splash — IP + web UI port + mDNS hostname drawn during the
  boot window before Buttons/Satellite/Companion claims the device. `dpx-deck-splash.service`, own venv,
  low-priv `dpx-splash` user (`buttons` group only). Required two hardware-only fixes CI couldn't catch:
  the `streamdeck` library needs `libhidapi-libusb0` + a `/dev/bus/usb/*` udev rule, not hidraw; hostname
  now chunks onto keys on word boundaries instead of a fixed character count.
- **Phase 2/3** (hardware-validated): a stage-then-GO config screen. MODE key cycles the *pending* selection
  through Buttons → Satellite → Companion (color-coded, skips Companion if not installed); NET toggles
  staged DHCP ↔ static; SUBNET cycles `/24 /22 /16 /8`; holding an octet key spins its value (locked unless
  NET is staged to static); GO commits mode + network together as one operation. Reached through
  `dpx-buttonode-ui.py --apply-mode <value>` / `--toggle-net` / `--pin-static <ip>[/prefix]` via a
  narrowly-scoped `/etc/sudoers.d/dpx-splash` rule.
  `dpx-deck-splash.service` `Conflicts=` all three mode services (not just Buttons), since Satellite and
  Companion both draw to the deck themselves once active. **Known limitation:** the config screen only
  shows while the splash service is actually running — before any mode has claimed the device. Switching
  *out of* an active mode still needs the web UI or SSH; switching *into* a different mode from the config
  screen (before one is active) works via MODE+GO.
  Two real bugs found and fixed during hardware validation: GO silently no-op'd if the selected mode's
  service had died while the persisted mode string stayed unchanged (fixed by checking actual service
  liveness, not just the string); the SSH key's original hold-to-reveal design turned out impractical in
  practice (a finger on the key covers the text it's revealing) — changed to press-to-toggle.

### Network Discovery Page
**Status:** partially done — Nodes tab shipped in v0.5.0 (LAN discovery via web UI); full server-side subnet scan still `- [ ]`

From any buttonode's web UI, show all other buttonodes visible on the local network. Server-side subnet scan (ARP table or `avahi-browse`) so there are no browser security restrictions. Rendered as a list of clickable links.

---

## General

- [x] code / [x] hardware test — **Security: SSH exposure, fixed 2026-08-25, hardware-validated
  2026-08-28/29.** Was: every image shipped SSH enabled with the hardcoded root password `1234`, unrotated
  per build. Now: SSH ships **disabled**, no hardcoded credential; `dpx-init-ssh.service` generates a
  random per-device password on first boot, revealed only via press-to-toggle on the deck splash's SSH key
  (never shown on the web UI); every SSH-tab action requires the current root password. See README's SSH
  section and AGENTS.md gotcha #10a for the full design. Hardware testing on a genuinely fresh flash found
  a real gap the code review hadn't caught: disabling only `ssh.service` left SSH fully reachable the
  entire time via Ubuntu's `ssh.socket` (socket activation starts `ssh.service` on demand regardless of its
  own disabled state) — fixed in both the Packer provisioning and the web UI's toggle.
- [ ] **Investigate: unexplained SSH-enabled state found on a genuinely fresh rockpi-s flash (2026-08-30).** Build-time provisioning, first-boot scripts, and unauthenticated-toggle theories have all been checked and ruled out with evidence (see AGENTS.md gotcha #26) — root cause still unknown. Needs a device with SSH/console access from first boot to actually catch the moment it flips, rather than reasoning about it after the fact.
- [ ] First-boot wizard (hostname confirmation, mode selection: Buttons vs Satellite)
- [ ] `/status` JSON endpoint for scripting/monitoring
- [ ] Make `full` variant opt-in on automated releases — add `build-full` boolean input to `release-action.yaml` so the full image is only built when explicitly requested, not on every Buttons version bump (currently doubles CI time)

---

## On-Device Auto-Update

**Status:** code complete; Updates tab check verified on real hardware 2026-08-29 (found and fixed a real
bug — Companion's check queried a GitHub repo with zero releases, always reported "unknown"; real source is
a Bitfocus-hosted API). Apply paths and the crash-recovery drill not yet exercised on hardware. `- [x]` code
/ `- [x]` check hardware-tested / `- [ ]` apply + crash-recovery hardware test

When the unit can see the internet, offer to update itself in-place. No custom server needed — the GitHub Releases API is the source of truth. No full image re-flash (not feasible OTA) — updates target only the Python UI file initially.

New **Updates** tab in `dpx-buttonode-ui.py` covers all four components: the
`dpx-buttonode-ui.py`/`dpx-deck-splash.py` pair self-update with a
validate-then-atomic-swap-then-restart flow, backed by a boot-attempt
counter that auto-restores the last known-good backup if the new file
crash-loops on startup. Buttons updates by downloading and `dpkg -i`-ing the
latest `.deb` from the `buttons-deb-mirror` release, restarting the service
only if Buttons is the currently active mode. Satellite and full Companion
(via new `scripts/update-satellite.sh` / `scripts/update-companion.sh` —
deliberately not reuses of the install scripts, which unconditionally
force-switch mode) run as detached `systemd-run --no-block` background jobs
with log/status files the Updates tab polls, and likewise only restart their
service if it's already the active mode. Full scope, not a minimal
self-updater, per explicit decision.

### Scope

| Component | Feasibility | Phase |
|---|---|---|
| `dpx-buttonode-ui.py` (web UI) | Easy — single file, atomic replace + service restart | 1 |
| Bitfocus Buttons USB Relay DEB | Medium — download `.deb` from mirror release, `dpkg -i` | 2 |
| Companion Satellite | Harder — re-run upstream install.sh | 3 |

### How It Works

**Version source:** `GET https://api.github.com/repos/dubpixel/dpx_buttonode/releases/latest` — parse `tag_name`, compare against `DPX_VERSION` from `/etc/dpx-buttonode-release`. Unauthenticated GitHub API, 60 req/hr limit — a 1h TTL cache keeps this well within bounds.

**Internet check:** `urllib.request.urlopen("https://api.github.com", timeout=3)` — pure stdlib, no new dependencies.

**Boot check:** Background daemon thread (30s startup delay to let network settle) calls `get_update_status()` and persists result to `/var/lib/dpx-update-status` (JSON). UI reads the cached file — no blocking.

**Apply mechanism (Phase 1):**
1. Download raw `dpx-buttonode-ui.py` from `https://raw.githubusercontent.com/dubpixel/dpx_buttonode/{latest_tag}/src/dpx-buttonode-ui/dpx-buttonode-ui.py` to `/tmp/`
2. Validate: file size > 1000 bytes, contains `PORT = 8080` sentinel
3. `os.replace()` atomic swap to `/usr/local/bin/dpx-buttonode-ui.py`
4. `systemd-run --no-block systemctl restart dpx-buttonode-ui` (existing pattern from `write_networkd_config`)
5. Update `DPX_VERSION` in `/etc/dpx-buttonode-release`

**UI flow:**
- Footer/Status tab shows a badge if an update is available
- "Check Now" button → POST `/updates/check` → invalidates cache, re-runs check
- "Update UI" button (only when update available) → POST `/updates/apply` → apply + restart → "please wait" page with meta-refresh

### Implementation Notes

- All changes in `dpx-buttonode-ui.py` only — reuse `_cached()`, `run()`, `_cache_lock`, and the `systemd-run` restart pattern already present
- Branch from `main` (not from `feature/` branches) so the raw download URL resolves to a real release tag
- Offline is graceful: no badge, no crash, just silent skip

