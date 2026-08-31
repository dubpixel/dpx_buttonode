
---
## [0.8.0](https://github.com/dubpixel/dpx_buttonode/compare/0.7.0...0.8.0) (2026-08-30)

> Real Raspberry Pi 4/5 support via the official Raspberry Pi OS (not Armbian), plus an opt-in
> Companion Dashboard kiosk display — both hardware-validated, with a string of real bugs found
> and fixed live, the most important being a Python 3.13 stdlib removal that was silently
> crash-looping the web UI on every Raspberry Pi OS build all session.

### Upgrade Steps
* None — existing Armbian-board units are unaffected. Reflash to pick up Raspberry Pi OS/Pi 4/5
  support and the Companion Dashboard feature.

### Breaking Changes
* None

### New Features
* Real Raspberry Pi OS build pipeline for Pi 4/5 (`raspios-builder.yaml`) — parallel to the
  existing Armbian pipeline, not a replacement
* Companion Dashboard: opt-in kiosk display toggle, Toggle Fullscreen (F11 via `xdotool`),
  low-RAM warning, deck splash `D` status key
* Persistent web UI status bar (version/mode/RAM) across every tab
* Uptime + RAM cards on the Status tab

### Bug Fixes
* The actual root cause of every Pi 4 "web UI unreachable" symptom this pass: Python 3.13
  removed the stdlib `crypt`/`spwd` modules — fixed with a direct `ctypes` binding to the
  system's real `libcrypt`
* Raspberry Pi OS's `userconfig.service` interactive first-boot prompt (masked)
* Raspberry Pi OS's cloud-init stalling boot searching for a datasource (disabled)
* `apt-get install xserver-xorg` silently pulling in a display manager and hijacking the boot
  target (fixed with `--no-install-recommends` + explicit `systemctl set-default`)
* `adduser --system` needing `--group` to get a matching group
* `systemctl disable --now` failing inside the Packer chroot on Raspberry Pi OS Trixie's systemd

### Performance Improvements
* None this pass

### Other Changes
* Pi OS build artifacts renamed `rpi4-5-dpx-buttonode-...` (was `rpi-...`) for clarity
* Packer source block renamed from `"armbian"` to `"base"` — it builds both pipelines, the old
  name made every Pi OS build log read `arm-image.armbian: ...`
* See `AGENTS.md` gotchas #17-26 for full technical detail behind every fix above

