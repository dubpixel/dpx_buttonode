# Action Plan — 2026-08-31

Working list for issues #10, #11, #12, #13, #14, #15, #16, #17. All of #12-17 came
from Josh's real-hardware testing notes on the Pi 4 build — since they're all in
shared code (`dpx-buttonode-ui.py` / deck splash), assume they apply to the Armbian
side too unless proven otherwise during implementation.

---

## Quick, direct fixes (no investigation needed, do first)

### #16 — Status page IP address box too small
CSS-only. The IP address card in `render_status()`'s grid wraps a full IPv4 address
(`192.168.68.75`). Widen the card or drop the font size slightly. Trivial, do
immediately.

### #13 — Dashboard should start fullscreen
**Root cause confirmed, not just suspected.** `install-dashboard.sh`'s `.xinitrc`
launches `companion-dashboard --kiosk --no-sandbox` — but `companion-dashboard`'s
own `main.js` checks `process.argv.includes('--kiosk-mode')`, not `--kiosk`. Wrong
flag entirely, so kiosk mode (fullscreen + auto-start web server) never actually
triggers. One-line fix: `--kiosk` → `--kiosk-mode`.

**This also unlocks #15** (see below) — `main.js` line ~437 auto-starts Dashboard's
own web server on port 80 specifically when kiosk mode is detected. Do this fix
before #15, not after.

---

## Needs source investigation before implementing

### #14 — Network settings don't persist across reboots
Josh's report: DHCP/static has to be reselected every boot. Need to verify before
assuming root cause:
- Does `pin_static()`/`toggle_net()` in `dpx-buttonode-ui.py` actually write a
  persistent `/etc/systemd/network/*.network` file, or does it only apply live
  without anything read back correctly at next boot?
- Does `dpx-deck-splash.py`'s `state["net_pending"]` initialization
  (`get_current_net_mode()`) correctly read back whatever was persisted, or does
  it default to something else on a fresh splash session?
- Cross-check against gotcha #6 (Netplan/networkd conflict) — the fix there was
  about *applying* a static config without netplan fighting it; verify it also
  *persists* correctly across a real reboot, not just survives that one `apply`.

Read the actual code path before writing a fix — this might already mostly work
and Josh hit one specific broken case, or it might be genuinely never persisting.

### #15 — Dashboard link in the web UI
Confirmed via `companion-dashboard` source: `/control` route exists
(`webServer.js`), served on the same web server kiosk mode auto-starts on port 80
(`main.js`). Depends on #13's fix landing first — without the correct
`--kiosk-mode` flag, that server never starts, so there's nothing to link to yet.

Once #13 is fixed: add a link in `render_mode()`'s Dashboard section, same pattern
as the existing Companion `open :8000 ↗` link — `http://<hostname-or-ip>/control`
(port 80, so no `:port` suffix needed in the URL). Only show it while
`dashboard_enabled()` is true, same gating as the Toggle Fullscreen button.

---

## Needs live device access

### #10 — Companion doesn't pick up Stream Deck after mode switch (Pi 4)
Confirmed real (issue #10 has the detail). USB-level detection is fine, mode
switch succeeds, the known gotcha #14 fix (`udevadm trigger` via power-cycle-deck)
didn't resolve it. **Blocked on real SSH access** — user offered to enable SSH via
the normal deck-key-reveal flow and hand over credentials directly (no debug
build needed this time). Once in: check `/dev/hidraw*` presence directly and
`journalctl -u companion` for what Companion itself is actually seeing/rejecting.

### #17 — D key doesn't launch Dashboard or reflect running state
Two symptoms, likely two different explanations:
- **"Doesn't launch"** — the D-key toggle feature (`--toggle-dashboard`, commit
  `56baa75`) postdates every currently-flashed device. Needs a fresh build from
  `main` + reflash before this can even be tested. Not necessarily a bug yet —
  rule out "no build exists" before assuming the toggle code itself is broken.
- **"Doesn't reflect state"** — `draw_dashboard_key()`/`dashboard_active()`
  predates `56baa75` and should already be live on current hardware. If it's
  genuinely wrong (not just "toggle does nothing because old build"), that's a
  real, separate bug — check `systemctl is-active dpx-dashboard` against what the
  key actually shows once there's console/SSH access to a device with Dashboard
  installed.

---

## Needs design + implementation

### #11 — Deck splash never recovers if a mode service's Restart=on-failure exhausts
**Decision made: event-driven, not polling** (lower resource use, matches the
user's stated preference). Direction: an `OnFailure=` hook on the mode services,
scoped carefully so it only fires on *final* exhaustion (systemd's
`StartLimitBurst`), not every transient retry attempt — firing on every retry
would fight the mode service's own recovery and thrash the deck display.

### #12 — Auto-start chosen mode + Dashboard on boot
**Architecturally the same problem as #11, just the inverse case.** Right now,
`dpx-deck-splash.service` and all three mode services are all `WantedBy=
multi-user.target` — they race at boot, and `Conflicts=` just stops whichever
loses. There's no deterministic "the user picked Satellite last time, so
Satellite should win the race, not splash" logic — it's luck-of-the-timing today.
That's very likely *why* Josh is asking for this: it's not that auto-start is
missing entirely (an enabled mode service already restarts on every boot via
normal systemd semantics), it's that splash sometimes wins the race and blocks it
without a GO press.

**Recommend designing #11 and #12 together, not as two separate patches** — both
need the same underlying coordinator logic: "exactly one of {a mode service,
deck-splash} should be running, preferring the persisted mode if one is set,
falling back to splash only if none is." Solving that cleanly handles both the
"mode dies for good → splash should come back" case (#11) and the "boot race →
the right thing should win automatically" case (#12) with one mechanism instead
of two bolted-on fixes that could disagree with each other.

Dashboard's own boot-time auto-start (the "and dashboard on/off" half of #12) is
simpler and independent of the above — it's just "should `dpx-dashboard.service`
be enabled or not," already a persisted systemd state via `set_dashboard_enabled()`,
so this half may already work correctly today. Verify before building anything
new for it.

---

## Suggested order

1. #16 (trivial, 5 min)
2. #13 (one-line flag fix, confirmed root cause)
3. #15 (depends on #13, otherwise straightforward)
4. #14 (needs a read-the-code pass first, then likely a real fix)
5. #11 + #12 together (the real design work — biggest single piece here)
6. #17's "doesn't launch" half — verify once a fresh build exists (falls out of #11/#12 work naturally, since that's a rebuild anyway)
7. #10 and #17's "doesn't reflect state" half — both need live device access, batch them into one SSH session once available
