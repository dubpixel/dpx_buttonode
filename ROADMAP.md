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
**Status:** Phase 1 hardware-validated (2026-08-24, Stream Deck MK.2); Phase 2/3 code complete, not yet hardware-tested `- [x]` Phase 1 / `- [x]` Phase 2 code / `- [x]` Phase 3 code / `- [ ]` Phase 2/3 hardware test

Draw device status directly onto the attached Stream Deck's keys via HID, instead of requiring SSH or the
web UI to find a fresh unit on the network.

- **Phase 1** (hardware-validated): read-only splash — IP + web UI port + mDNS hostname drawn during the
  boot window before Buttons/Satellite/Companion claims the device. `dpx-deck-splash.service`, own venv,
  low-priv `dpx-splash` user (`buttons` group only). Required two hardware-only fixes CI couldn't catch:
  the `streamdeck` library needs `libhidapi-libusb0` + a `/dev/bus/usb/*` udev rule, not hidraw; hostname
  now chunks onto keys on word boundaries instead of a fixed character count.
- **Phase 2/3** (code complete, pending hardware test): a third key row (when present) adds MODE and NET
  action buttons — MODE cycles Buttons → Satellite → Companion (skipping Companion if not installed), NET
  toggles DHCP ↔ last-known-static, both debounced. The splash process stays unprivileged (`buttons` group
  only) and reaches system state through exactly two fixed, argument-free commands
  (`dpx-buttonode-ui.py --cycle-mode` / `--toggle-net`) via a narrowly-scoped `/etc/sudoers.d/dpx-splash`
  rule — no argument value for a bug or compromise to smuggle through.
  `dpx-deck-splash.service` now `Conflicts=` all three mode services (not just Buttons), since Satellite
  itself draws to the deck once connected to a Companion server. **Known limitation:** the MODE/NET keys
  only work while the splash service is actually running — i.e. in Satellite or Companion mode. Buttons
  mode conflicts with the splash service by design, so switching *out of* Buttons still needs the web UI
  or SSH.

### Network Discovery Page
**Status:** partially done — Nodes tab shipped in v0.5.0 (LAN discovery via web UI); full server-side subnet scan still `- [ ]`

From any buttonode's web UI, show all other buttonodes visible on the local network. Server-side subnet scan (ARP table or `avahi-browse`) so there are no browser security restrictions. Rendered as a list of clickable links.

---

## General

- [x] code / [ ] hardware test — **Security: SSH exposure, fixed 2026-08-25.** Was: every image shipped SSH
  enabled with the hardcoded root password `1234`, unrotated per build. Now: SSH ships **disabled**, no
  hardcoded credential; `dpx-init-ssh.service` generates a random per-device password on first boot, shown
  on the web UI's new **SSH** tab and on the deck splash screen until changed; every SSH-tab action requires
  the current root password (the web UI itself has no login, so this is load-bearing, not decorative). See
  README's SSH section and AGENTS.md gotcha #10a for the full design. Not yet validated on real hardware —
  first-boot generation, the deck's password key, and the web UI flow all still need a real test.
- [ ] First-boot wizard (hostname confirmation, mode selection: Buttons vs Satellite)
- [ ] `/status` JSON endpoint for scripting/monitoring
- [ ] Make `full` variant opt-in on automated releases — add `build-full` boolean input to `release-action.yaml` so the full image is only built when explicitly requested, not on every Buttons version bump (currently doubles CI time)

---

## On-Device Auto-Update

**Status:** planned — `- [ ]`

When the unit can see the internet, offer to update itself in-place. No custom server needed — the GitHub Releases API is the source of truth. No full image re-flash (not feasible OTA) — updates target only the Python UI file initially.

### Scope

| Component | Feasibility | Phase |
|---|---|---|
| `dpx-buttonode-ui.py` (web UI) | Easy — single file, atomic replace + service restart | 1 |
| Bitfocus Buttons USB Relay DEB | Medium — download `.deb` from mirror release, `dpkg -i` | 2 |
| Companion Satellite | Harder — re-run upstream install.sh | 3 |

### How It Works

**Version source:** `GET https://api.github.com/repos/dubpixel/dpx_buttons_armbian/releases/latest` — parse `tag_name`, compare against `DPX_VERSION` from `/etc/dpx-buttonode-release`. Unauthenticated GitHub API, 60 req/hr limit — a 1h TTL cache keeps this well within bounds.

**Internet check:** `urllib.request.urlopen("https://api.github.com", timeout=3)` — pure stdlib, no new dependencies.

**Boot check:** Background daemon thread (30s startup delay to let network settle) calls `get_update_status()` and persists result to `/var/lib/dpx-update-status` (JSON). UI reads the cached file — no blocking.

**Apply mechanism (Phase 1):**
1. Download raw `dpx-buttonode-ui.py` from `https://raw.githubusercontent.com/dubpixel/dpx_buttons_armbian/{latest_tag}/src/dpx-buttonode-ui/dpx-buttonode-ui.py` to `/tmp/`
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

