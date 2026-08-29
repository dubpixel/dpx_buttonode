# First-Boot / Fresh-Image Test Plan

A running checklist of everything that needs verifying on a **truly fresh
flash** — a blank SD card, first boot, no prior state — before the next real
Packer image build is considered validated for release.

Why this file exists: Packer builds + SD flashing are slow, so feature work
gets validated by hand-patching one already-initialized test unit instead.
That's fine for fast iteration, but it means first-boot-only logic (anything
gated behind a marker file, or that only runs once) never actually gets
re-exercised — the test unit's markers (`/var/lib/dpx-ssh-initialized`,
`/etc/dpx-mode`, etc.) were set back on its original 2026-08-24 flash and
never cleared. This file is where that gap gets tracked, so when we finally
spend a real image-build-and-flash cycle, we walk it once, top to bottom,
instead of relying on memory or re-discovering gaps live.

**Use a separate, genuinely blank SD card for this pass** — not
`dpx-buttonode-2199`, which is the fast hand-iteration box and already has
stale first-boot state.

**Do not check items off from memory or from testing the hand-patched
unit.** Only check something off after observing it on an actual fresh boot.

---

## Items queued since the last real build (`215f0bc`, 2026-08-24)

**2026-08-28/29 update:** `dpx-buttonode-2199` got a genuine fresh
re-flash (full variant, `061d494`) for this pass — same physical unit/
hostname (MAC-derived, so that's expected), but confirmed genuinely fresh
via a changed SSH host key, fresh `dpx-init-ssh` marker/password, and a
truly-first boot-state file. Not the same thing as the old rule's warning
against reusing the stale hand-patched instance — this was flashed clean.
Items below checked off only where actually observed this pass; several
real bugs were found and fixed live (see commits `225f94b`, `8fb0da5`,
`bd166e4`, `0026796`) — re-verify on the *next* fresh flash once those
land in a build, since none of today's fixes were themselves present in
the image that was tested.

- [x] `dpx-set-hostname.service` — hostname resolved as
  `dpx-buttonode-2199.local` via mDNS on first boot, chunked on word
  boundaries correctly
- [x] `dpx-init-ssh.service` — random password generated once, written to
  `/etc/dpx-initial-ssh-password` (root:buttons, 0640), marker present —
  **but SSH itself was NOT actually disabled** (found live: `ssh.socket`
  left listening on :22 independently of `ssh.service`'s disabled state —
  fixed in `225f94b`, not yet re-verified on a fresh flash with the fix in)
- [x] Deck splash Phase 1 — IP / mDNS hostname rendered correctly on the
  Stream Deck during the boot window, confirmed via camera
- [x] Deck splash Phase 2/3 stage-then-GO flow — MODE key cycles
  Buttons → Satellite → Companion correctly (confirmed via camera, all
  three colors), NET key toggles static/DHCP correctly (confirmed via
  camera), SUBNET confirmed working (visual read). Octet hold-to-edit and
  the full GO-commits-network path were **not** exercised this pass
  (deliberately avoided applying network changes with no physical-console
  fallback available)
- [x] SSH key hold-to-reveal — worked, but confirmed impractical in
  practice ("very tricky" to read with a finger covering the key) —
  redesigned to press-to-toggle instead (`3ddb30f`), re-verified working
  after the change
- [ ] Default mode on first boot is Satellite, not Buttons — not directly
  observed this pass (mode was already switched by the time testing
  started)
- [ ] Web UI SSH tab, end to end (enable/change-password/reachability) —
  the enable/disable halves were verified as part of fixing `225f94b`, but
  not the full change-root-password flow on this fresh instance
- [x] Updates tab — Check Now hits real APIs and renders real
  current/latest data for all four components — **but Companion's check
  was completely broken** (queried a GitHub repo with zero releases,
  always showed "unknown") — fixed in `0026796`, re-verify on next flash
- [ ] Updates tab — real apply (deliberately not attempted this pass)
- [ ] Updates tab — crash-recovery drill (deliberately not attempted this
  pass)
- [x] Full-variant Companion: install completed via the real Packer
  pipeline (confirmed the `46ff589` fnm-ordering fix actually works end to
  end — first time Companion+Satellite coexisted correctly straight out of
  a from-scratch build), mode switching into Companion works from the web
  UI and the deck, **but** switching back into a mode after its service
  had died did NOT work — GO silently no-op'd because the persisted mode
  string alone doesn't prove the service is actually running — fixed in
  `8fb0da5`/`bd166e4`, not yet re-verified on a fresh flash

---

## Process

1. Build both `variant=lite` and `variant=full` images (draft/prerelease,
   per the existing untested-build convention).
2. Flash each onto its own blank card.
3. Walk this checklist for the applicable variant.
4. Note any failures as new commits/fixes, then re-flash and re-check only
   the affected items — no need to redo a whole passing checklist for an
   unrelated fix.
5. Add new items here whenever a change touches first-boot or whole-device
   behavior, so the next full pass stays comprehensive.
