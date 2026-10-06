# Known-good field reference: commit 8080ce3

Captured 2026-10-06 from a real unit (`dpx-buttonode-2199`) that ran a live
show at iHeart and has been reliable for weeks. Used as ground truth while
diagnosing the `fix/deck-splash-first-boot-blank` regression (see PR for
that branch, and gotcha entries in `AGENTS.md` for the full story).

A full compressed disk image (`dd`'d live over SSH, ~31GB raw → ~1.7GB
compressed) is kept locally, not in git — binary images are gitignored
and belong in a release, not a commit. Ask the maintainer if you need it.

## Build metadata (`/etc/dpx-buttonode-release`)

```
DPX_VERSION=0.7.0
BUTTONS_VERSION=0.1.0-beta.4
GIT_BRANCH=main
GIT_COMMIT=8080ce3
BUILD_DATE=2026-08-30
VARIANT=full
COMPANION_VERSION=5.0.4+9717-stable-a69c14dec2
SATELLITE_VERSION=3.4.0
DASHBOARD_INSTALLED=1
```

## State at capture time

- Hostname: `dpx-buttonode-2199`
- `/etc/dpx-mode`: `satellite`
- `/etc/dpx-satellite.conf`: empty — Satellite has never been pointed at a
  Companion host on this unit. Confirms the device is used primarily for
  its deck-splash screen (IP/hostname display), not an active Satellite
  connection — see below.
- Network: plain DHCP via the default Armbian-generated Netplan config, no
  custom overrides.
- `/var/lib/dpx-mode-autostart-disabled`: does not exist — not meaningful
  on this build, since `dpx-mode-select.service` doesn't exist yet at this
  commit (see below).

## Why this build matters architecturally

This commit **predates `dpx-mode-select.service` entirely** (that
mechanism was added later, in `dcd21db`/issue #12, "start system
automatically"). On this build:

- `dpx-deck-splash.service` is simply `enabled` and stays the default —
  confirmed live: `satellite` was `inactive` while `dpx-deck-splash` was
  `active`, even though `/etc/dpx-mode` says `satellite`.
- A mode only starts when explicitly triggered (e.g. a GO press on the
  deck) — never automatically resumed on boot.

This is the real reason it's been reliable for weeks despite never having
a configured Companion host: the splash screen is always what's actually
on the deck by default, which is exactly what the project's own stated
design goal has always been ("no web UI or SSH required for first setup").

The newer `dpx-mode-select.service` flipped that default — auto-resuming
the persisted mode on every boot — which broke the guarantee on a fresh
flash (Satellite starts "successfully" per systemd, shows nothing, and
nothing falls back to splash). Fixed in `fix/deck-splash-first-boot-blank`
by pre-seeding `/var/lib/dpx-mode-autostart-disabled` on fresh images,
restoring this exact proven-safe default.
