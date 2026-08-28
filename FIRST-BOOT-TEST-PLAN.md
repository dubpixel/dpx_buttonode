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

- [ ] `dpx-set-hostname.service` — hostname resolves as
  `dpx-buttonode-XXXX.local` via mDNS on first boot, chunked on word
  boundaries (not mid-word)
- [ ] `dpx-init-ssh.service` — a random root password is generated exactly
  once on first boot, written to `/etc/dpx-initial-ssh-password`
  (root:buttons, 0640), and SSH itself stays **disabled**
- [ ] Deck splash Phase 1 — IP / mDNS hostname / web UI port render
  correctly on the Stream Deck during the boot window, before any mode
  service claims the device
- [ ] Deck splash Phase 2/3 stage-then-GO flow — MODE key cycles
  Buttons → Satellite → Companion (skips Companion on lite variant), NET
  key toggles DHCP/static, SUBNET key cycles /24 /22 /16 /8, octet keys are
  locked unless NET is staged to static, hold-to-edit actually advances the
  octet, GO commits the staged mode+network together
- [ ] SSH key hold-to-reveal on the deck shows the first-boot password;
  releasing returns to the neutral "SSH" label; the password is never
  visible anywhere on the web UI
- [ ] Default mode on first boot is Satellite, not Buttons
- [ ] Web UI SSH tab, end to end: enable SSH with the initial password,
  change the root password, confirm the initial-password file gets deleted
  and SSH is reachable with the new password
- [ ] Updates tab — Check Now hits GitHub and renders real current/latest
  data for all applicable components (Companion card only on full variant)
- [ ] Updates tab — at least one real apply (Buttons `.deb` is the
  lowest-risk one to actually click)
- [ ] Updates tab — deliberate crash-recovery drill: point a self-update at
  a broken build (or otherwise force `dpx-buttonode-ui.py` to crash on
  startup) and confirm the boot-attempt counter restores the last `.bak`
  within the retry window instead of restart-looping forever. Safe to do
  here specifically because the card is disposable — do not do this on
  `dpx-buttonode-2199`.
- [ ] Full-variant only: Companion install completes, `companion.service`
  installed-but-disabled by default (Satellite stays the default mode),
  mode switching into/out of Companion works from both the web UI and the
  deck

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
