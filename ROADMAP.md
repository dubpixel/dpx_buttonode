# dpx-buttnode Roadmap

Loose collection of planned improvements and ideas. Not a commitment, not a schedule — just a living list.

---

## Discovery & Setup UX

### `/label` — Self-Printed QR Label Page
**Status:** planned — `- [ ]`

Each buttnode already knows its own hostname (`dpx-buttnode-XXXX.local`) at runtime via Avahi/mDNS. The problem is you can't pre-print a label before first boot because the hostname is MAC-derived.

**Solution:** Add a `/label` route to `dpx-buttnode-ui.py` that renders a clean printable page containing:
- A QR code pointing to `http://dpx-buttnode-XXXX.local:8080`
- The `.local` URL printed in large text below it
- A print button (hides chrome, triggers `window.print()`)

Workflow: boot the unit → open its IP in a browser → go to `/label` → print → stick on box.

No external libraries needed. A pure-JS QR generator (e.g. `qrcode.js` inlined) handles the QR client-side.

---

### Network Discovery Page
**Status:** partially done — Nodes tab shipped in v0.5.0 (LAN discovery via web UI); full server-side subnet scan still `- [ ]`

From any buttnode's web UI, show all other buttnodes visible on the local network. Server-side subnet scan (ARP table or `avahi-browse`) so there are no browser security restrictions. Rendered as a list of clickable links.

---

## General

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
| `dpx-buttnode-ui.py` (web UI) | Easy — single file, atomic replace + service restart | 1 |
| Bitfocus Buttons USB Relay DEB | Medium — download `.deb` from mirror release, `dpkg -i` | 2 |
| Companion Satellite | Harder — re-run upstream install.sh | 3 |

### How It Works

**Version source:** `GET https://api.github.com/repos/dubpixel/dpx_buttons_armbian/releases/latest` — parse `tag_name`, compare against `DPX_VERSION` from `/etc/dpx-buttnode-release`. Unauthenticated GitHub API, 60 req/hr limit — a 1h TTL cache keeps this well within bounds.

**Internet check:** `urllib.request.urlopen("https://api.github.com", timeout=3)` — pure stdlib, no new dependencies.

**Boot check:** Background daemon thread (30s startup delay to let network settle) calls `get_update_status()` and persists result to `/var/lib/dpx-update-status` (JSON). UI reads the cached file — no blocking.

**Apply mechanism (Phase 1):**
1. Download raw `dpx-buttnode-ui.py` from `https://raw.githubusercontent.com/dubpixel/dpx_buttons_armbian/{latest_tag}/src/dpx-buttnode-ui/dpx-buttnode-ui.py` to `/tmp/`
2. Validate: file size > 1000 bytes, contains `PORT = 8080` sentinel
3. `os.replace()` atomic swap to `/usr/local/bin/dpx-buttnode-ui.py`
4. `systemd-run --no-block systemctl restart dpx-buttnode-ui` (existing pattern from `write_networkd_config`)
5. Update `DPX_VERSION` in `/etc/dpx-buttnode-release`

**UI flow:**
- Footer/Status tab shows a badge if an update is available
- "Check Now" button → POST `/updates/check` → invalidates cache, re-runs check
- "Update UI" button (only when update available) → POST `/updates/apply` → apply + restart → "please wait" page with meta-refresh

### Implementation Notes

- All changes in `dpx-buttnode-ui.py` only — reuse `_cached()`, `run()`, `_cache_lock`, and the `systemd-run` restart pattern already present
- Branch from `main` (not from `feature/` branches) so the raw download URL resolves to a real release tag
- Offline is graceful: no badge, no crash, just silent skip

