# dpx Agent Workflow & Documentation Standards - v1d6

This document provides operational directives for AI coding assistants (GitHub Copilot, Claude Code, Cursor, etc.) working on dubpixel projects. These rules ensure consistent workflow automation, code quality, and documentation maintenance across all repositories.

---

## PROJECT: dpx-buttonode

**Status:** `feature/deck-hid-splash` carries everything — the rename, the Full/Lite
Companion variant system, the deck HID splash feature (all 3 phases,
hardware-validated), the SSH security overhaul, and the on-device
auto-update system. Not yet merged to `main`. Draft/prerelease test builds
only so far; see `FIRST-BOOT-TEST-PLAN.md` for the checklist a real fresh
flash needs before this is release-ready.  
**Branch:** `feature/deck-hid-splash`  
**Version File:** `VERSION` (0.7.0)

**Branch stack:**
- `main` — **stale.** Predates the `dpx_buttnode`→`dpx_buttonode` rename
  and everything since. Do not branch new work off `main`.
- `refactor/rename-dpx-buttonode` — superseded. The rename it did landed
  on `feature/deck-hid-splash` too; this branch itself is no longer where
  active work happens.
- `feature/deck-hid-splash` — **the active branch.** Contains the rename,
  the v0.6.0 Full/Lite Companion variant system, and everything documented
  in `CHANGELOG.md`'s `[0.7.0]` entry. This is what gets built/tested/
  eventually merged.

**Immediate next steps:**
1. Build a fresh full-variant image from current `feature/deck-hid-splash`
   HEAD and walk `FIRST-BOOT-TEST-PLAN.md` on a genuinely blank flash —
   several real bugs were found and fixed live during 2026-08-28/29
   hardware testing (see CHANGELOG `[0.7.0]` Fixed section) that were
   never themselves present in the image actually tested that day.
2. Merge to `main` once a fresh-flash pass comes back clean.

**Open issues:**
- Issue #4: make Full variant opt-in on automated releases (`build-full`
  boolean input on `release-action.yaml` so cron only builds Lite)
- Issue #5: optional Companion Dashboard integration (scoping only)
- Issue #6: cross-platform (Armbian board matrix + separate Raspberry Pi
  OS path) support (scoping only)

---

### Architecture (2-minute summary)

Automated GitHub Actions build pipeline that produces flash-ready `.img.gz` images for ARM single-board computers with **Bitfocus Buttons USB Relay, Companion Satellite, and (Full variant) Companion** pre-installed, plus an opt-in Companion Dashboard kiosk display. Default mode is Companion Satellite (as of 2026-08-24 — was Buttons before); switch modes via the web UI, SSH, or the deck itself (Phases 2/3, hardware-validated — stage a mode with the octet keys, confirm with GO) — no re-flash needed.

**Two base-OS pipelines feed the same Packer customization stage** (`dpx-buttonode.pkr.hcl`) — this is deliberate, not two copies of the same thing: Armbian is for the non-Pi board families it actually supports well (Rockchip, Allwinner, Amlogic — e.g. `rockpi-s`, `orangepizero3`); real Raspberry Pi 4/5 hardware gets actual Raspberry Pi OS, never the Armbian `rpi4b`/`rpi5b` dropdown entries (Armbian's Pi support is secondary to the boards it's built for, especially for GPU/HDMI/VideoCore). Both pipelines download/build a base `.img`, then hand it to the identical Packer chroot stage:
- `.github/workflows/armbian-builder.yaml` — Armbian build framework compiles a minimal Ubuntu Noble base image per board (`armbian-board` input, ~30-60+ min compile).
- `.github/workflows/raspios-builder.yaml` — downloads the official Raspberry Pi OS Lite (64-bit) image directly from Raspberry Pi's own release manifest (same one Raspberry Pi Imager uses); one universal image covers Pi 4/5, no board matrix needed. Raspberry Pi OS ships two partitions (boot + root) vs. Armbian's one — see AGENTS.md gotcha #17 for why `image_mounts` has to differ per pipeline.

Packer then installs the Buttons `.deb`, the deck splash, Companion (Full variant only, must run before Satellite — gotcha #13), Companion Satellite, and the opt-in Dashboard kiosk — same provisioner sequence regardless of which OS pipeline produced the base image. The Buttons package is distributed as a `.tar.gz` from Bitfocus's auth-gated portal — this project solves that by maintaining a self-hosted mirror release (`buttons-deb-mirror`) in the repo, so CI only needs the built-in `GITHUB_TOKEN`. No Bitfocus credentials ever touch CI.

| Component | Tech/Location | Purpose | Notes |
|-----------|---------------|---------|-------|
| Packer build definition | HCL / `dpx-buttonode.pkr.hcl` | Chroot customization of the base image — shared by both OS pipelines | Uses `arm-image` plugin v0.2.7; targets 5/8 GB image (lite/full); `image_mounts` var must match the source image's partition count (gotcha #17) |
| Buttons install script | Bash / `scripts/install-buttons.sh` | Installs Buttons `.deb`, installs dpx-buttonode-ui + dpx-set-hostname, enables all services, registers mDNS | Runs as root inside Packer shell provisioner |
| Satellite install script | Bash / `scripts/install-satellite.sh` | Installs Companion Satellite from source, disables it (buttons is default), adds `satellite` user to `buttons` group | Runs after `install-buttons.sh`; needs network inside chroot; ~30-60 min |
| Hostname script | Bash / `scripts/dpx-set-hostname.sh` | Sets `dpx-buttonode-XXXX` hostname from MAC on first boot | Reads MAC from sysfs; oneshot service runs Before=network.target avahi-daemon.service |
| Web UI | Python / `src/dpx-buttonode-ui/dpx-buttonode-ui.py` | Device config UI on port 8080: hostname, DHCP/static network, USB devices, node discovery, **mode switch**, Dashboard toggle | Pure Python 3 stdlib; tabs: Status (incl. Uptime/RAM), Hostname, Network, Devices (incl. Dashboard toggle), Nodes, Mode, SSH, Updates |
| UI preview pages | HTML / `html/dpx-buttonode-ui-*.html` | Static mock previews of each UI tab for screenshots and dev reference | Moved to `html/` subfolder; file map in `.github/skills/screenshot-html-preview/SKILL.md` |
| Mode file | `/etc/dpx-mode` | Persists current mode (`buttons`, `satellite`, or `companion`) across reboots | Read by UI and by switch logic; written on mode change |
| Satellite config | `/etc/dpx-satellite.conf` | Persists Companion server HOST/PORT | Written by UI POST /satellite-config; also stages `/boot/satellite-config` |
| Download script | Bash / `scripts/download-buttons.sh` | Pulls `.tar.gz` from mirror release, extracts `.deb` | Primary: `gh release download`; fallback: `gh api /releases` list + `curl` |
| Mirror upload helper | Bash / `scripts/upload-mirror.sh` | LOCAL script — uploads new Bitfocus package to mirror release | Run by maintainer when new Buttons version drops; requires `gh` auth |
| Companion install script | Bash / `scripts/install-companion.sh` | Installs full Bitfocus Companion inside Packer chroot (Full variant only); disables service on install | Reads COMPANION_BUILD=stable; writes COMPANION_VERSION to `/etc/dpx-buttonode-release` |
| Build workflow (Armbian) | YAML / `.github/workflows/armbian-builder.yaml` | Reusable: builds Armbian + downloads package + runs Packer + uploads artifact | `armbian-board` + `variant` inputs (lite/full); artifact named `{board}-dpx-buttonode-{ver}-{variant}-{commit}`; retention 3 days |
| Build workflow (Raspberry Pi OS) | YAML / `.github/workflows/raspios-builder.yaml` | Reusable: downloads official Raspberry Pi OS Lite (64-bit) + runs the same Packer stage + uploads artifact | `variant` input only (no board matrix — one image covers Pi 4/5); artifact named `rpi-dpx-buttonode-{ver}-{variant}-{commit}`; retention 3 days; added 2026-08-29 for issue #6 |
| Release workflow | YAML / `.github/workflows/release-action.yaml` | Daily cron version check + matrix build + GitHub Release publish | Matrix: `board × variant` (rockpi-s + orangepizero3 × lite + full); version prefix-match on mirror asset name |
| Package mirror | GitHub Release / tag `buttons-deb-mirror` | Hosts the Bitfocus `.tar.gz` for CI to download | **Maintainer updates this when Bitfocus ships a new version** |
| Deck splash script | Python / `src/dpx-deck-splash/dpx-deck-splash.py` | Draws IP + mDNS hostname on the Stream Deck's keys during boot; stage-then-GO mode/network config via keypresses (Phases 2/3, hardware-validated) | NOT stdlib-only (unlike the UI) — own venv at `/opt/dpx-deck-splash/venv` (`streamdeck` + `Pillow`); SSH key is press-to-toggle reveal |
| Deck splash install script | Bash / `scripts/install-deck-splash.sh` | Provisions the venv, installs the script + `dpx-deck-splash.service`, creates the low-priv `dpx-splash` user in the `buttons` group | Runs after `install-buttons.sh` — needs the `buttons` group + hidraw udev rule that package creates |
| Dashboard install script | Bash / `scripts/install-dashboard.sh` | Installs `tomhillmeyer/companion-dashboard` as an opt-in X11/Electron kiosk display; installed but NOT enabled — web UI Devices tab toggles it | Runs on both variants (orthogonal to Buttons/Satellite/Companion, not gated by mode); `dpx-dashboard.service` runs as `User=root` (gotcha #20); needs `adduser --system --group` (gotcha #19) |

### Agent Rules (for this repo)

**Before ANY code change:**
1. Create feature branch from `main`: `feature/brief-description`
2. Bump `VERSION` file per semantic versioning (AGENTS.md §1)
3. Commit version bump standalone: `git commit -m "bump version to X.Y.Z"` + `git tag vX.Y.Z`

**While coding:**
- Never commit `.tar.gz`, `.deb`, `.img`, or `.img.gz` files — they are gitignored; use the mirror release
- Workflow YAML changes must be tested by manually triggering `armbian-builder.yaml` on one board before touching the matrix
- The `deb_path` variable in `dpx-buttonode.pkr.hcl` must always point to `artifacts/bitfocus-buttons-usb-relay-headless.deb` — that's the normalized name `download-buttons.sh` outputs
- Keep the `buttons-deb-mirror` release tag permanent — never delete it; it is the CI package source
- File header per AGENTS.md §3

**When done:**
- Update `CHANGELOG.md` with new version entry and date
- Update `VERSION` file
- Create PR per AGENTS.md §1 template
- Verify `armbian-builder.yaml` can still run `workflow_dispatch` manually without errors

### Critical Constraints

**MUST HAVE:**
- ✅ `buttons-deb-mirror` GitHub Release must always exist with a valid `.tar.gz` asset — CI fails without it
- ✅ `GITHUB_TOKEN` permissions `contents: read` on builder, `contents: write` on release job
- ✅ `qemu-user-static` installed on the runner before Packer runs (ARM64 chroot requirement)
- ✅ `avahi-daemon` installed inside the image (mDNS discovery on port 3040)
- ✅ `VERSION` file kept in sync with `CHANGELOG.md`

**DO NOT:**
- ❌ Add `BITFOCUS_EMAIL` / `BITFOCUS_PASSWORD` secrets — the mirror approach eliminates this entirely
- ❌ Commit binary files (`.deb`, `.tar.gz`, images) to git — use the mirror release
- ❌ Delete or rename the `buttons-deb-mirror` release tag — it breaks all CI builds
- ❌ Change the Packer output path `output-dpx-buttonode/` without updating the compression step in `armbian-builder.yaml`
- ❌ Modify the board matrix in `release-action.yaml` without confirming the board is in the Armbian supported list

### Key Decisions

- **Self-hosted mirror over portal auth:** Bitfocus Buttons USB Relay is closed-source with an auth-gated download portal and no public API docs. Rather than reverse-engineering the login flow and storing credentials as secrets, the maintainer manually uploads `.tar.gz` packages to a dedicated GitHub Release. CI downloads using the always-available `GITHUB_TOKEN`. Simple, reliable, zero secrets.
- **Packer over Armbian userpatches:** Image customization happens post-build via Packer chroot, not via Armbian's native overlay system. This decouples the Armbian build from the Buttons install — the Armbian image can be rebuilt independently, and Packer applies the same customization regardless of Armbian version changes.
- **Version detected from asset filename:** The release workflow determines the Buttons version by parsing the `.tar.gz` filename in the mirror release (e.g., `bitfocus-buttons-usb-relay-headless_0.1.0-beta.4_arm64.tar.gz` → `0.1.0-beta.4`). No API call required. Filename is the source of truth.
- **Orange Pi Zero family as default matrix:** Same boards as the reference project (`companion-satellite-armbian`). They're cheap, low-power, well-supported by Armbian, and ideal for a dedicated USB relay appliance.
- **SSH enabled by default:** Enabled so hardware testing and debugging don't require a serial adapter. Credentials: `root` / `1234` (Armbian forces password change on first login).

### Gotchas & Landmines

1. **Armbian build framework is large and slow:** The `git clone --depth=1` of `armbian/build` takes several minutes. The full compile step is 30-60+ minutes per board. Companion Satellite adds another 30-60 min (Node.js + Yarn build inside chroot). Don't expect fast CI feedback loops.
2. **`buttons-deb-mirror` must exist before first CI run:** Run `./scripts/upload-mirror.sh <tarball>` locally before triggering any workflow. The download step will fail with a 404 if the mirror release doesn't exist.
3. **Debian version notation uses `~` for pre-release:** The `.deb` inside the tarball uses `0.1.0~beta.4` (tilde) but the tarball filename uses `0.1.0-beta.4` (dash). `download-buttons.sh` handles this — don't try to parse the `.deb` filename directly.
4. **DO NOT disable IPv6:** Tried `ipv6.disable=1` in `armbianEnv.txt` and `NetworkManager ipv6.method=disabled` — both broke DHCP, the board got no IP at all. Armbian's network stack relies on IPv6 being present during interface bring-up. Leave networking alone.
5. **Packer `arm-image` plugin requires `sudo`:** All `packer init` and `packer build` calls must be prefixed with `sudo`. The plugin modifies loop devices and mounts.
6. **Netplan/networkd conflict on Armbian (Ubuntu Noble):** Armbian uses Netplan with `10-dhcp-all-interfaces.yaml` containing a wildcard `match: name: "e*"` DHCP config. `netplan apply` returns rc=1 when given a conflicting override file and deletes it. The working solution: write `/etc/systemd/network/09-dpx-<iface>.network` (the `09-` prefix sorts before Netplan's `10-`) AND delete `/run/systemd/network/10-netplan-all-eth-interfaces.network` before restarting networkd.
7. **`netplan version` is not a valid subcommand** on this Armbian build — use `Path("/usr/sbin/netplan").exists()` to detect Netplan instead.
8. **Satellite service name is `satellite`** (not `companion-satellite`). The official `pi-image/install.sh` creates a systemd unit named `satellite`. Never assume otherwise.
9. **`/boot/satellite-config` is a one-shot import.** Satellite reads it on startup and resets the file to prevent re-import on next boot. Our persistent store is `/etc/dpx-satellite.conf`. The UI writes both on every save.
10a. **SSH security fix, hardware-validated 2026-08-28.** Was: every image shipped SSH enabled with the hardcoded root password `1234`, not rotated per build — confirmed on hardware that Armbian's "forces password change on first login" never fires for scripted/automated SSH (only an interactive terminal), so the default stayed valid indefinitely. Now: `dpx-buttonode.pkr.hcl` does `systemctl disable --now ssh.socket` **and** `ssh.service` (SSH ships off, no hardcoded credential at all).

**Landmine found on a genuinely fresh flash 2026-08-28**: disabling only `ssh.service` is not enough. Ubuntu ships `ssh.socket` enabled alongside it — systemd listens on `:22` via the socket unit and lazily starts `ssh.service` on the first connection attempt (socket activation), regardless of the service's own enabled/active state. A fresh image with only `ssh.service` disabled was fully SSH-reachable the *entire time* — `systemctl is-enabled ssh` correctly said "disabled," but that told you nothing about actual reachability. Same gap existed in the web UI's SSH tab: `set_ssh_enabled(False)` only disabled `ssh.service`, so clicking "Disable SSH" didn't actually disable SSH — `ssh.socket` kept the door open. Fixed in both places: the Packer provisioning disables both units, and `ssh_enabled()`/`set_ssh_enabled()` in `dpx-buttonode-ui.py` now check/manage `ssh.socket` too (enabling only ever needs `ssh.service` directly; disabling must stop both). Lesson: `systemctl is-enabled <service>` is not the same question as "is this actually reachable" on any distro using socket activation — check what's actually listening (`ss -ltn`), not just the unit you assume is in front.

`scripts/dpx-init-ssh.sh` (new oneshot service `dpx-init-ssh.service`, mirrors `dpx-set-hostname.service`'s pattern) generates a random 10-char root password on first boot, writes it to `/etc/dpx-initial-ssh-password` (root:buttons, 0640 — group-readable by the same `buttons` group `dpx-splash` is already in for HID access, no new privilege grant). `dpx-buttonode-ui.py`'s new **SSH** tab (`get_initial_ssh_password()`/`ssh_enabled()`/`set_ssh_enabled()`/`change_root_password()`) lets you enable SSH or set a real password — **every action on that tab requires the current root password**, verified via `verify_root_password()` against `/etc/shadow` directly (`crypt`+`spwd`, stdlib — `crypt` is deprecated pending a future Python removal, revisit if the Armbian base Python version changes) — this check is load-bearing: the web UI has zero authentication of its own, so without it "enable SSH from the browser" would be worse than the old default, letting anyone on the LAN turn it on with a password of their choosing. **The generated password itself is deliberately never displayed on the web UI** — the SSH tab only tells you it exists and where to find it. The ONLY place it's ever revealed is `dpx-deck-splash.py`'s SSH key (between SUBNET and GO, decks with >=5 columns), and only while that key is physically held down (hold-to-reveal, reverts to a neutral "SSH" hint on release) — this was a deliberate hardening pass on top of the first cut, which *did* show it on the web page and was correctly called out as pointless (LAN access alone would've revealed it, no physical presence required). The initial-password file is deleted the moment `change_root_password()` succeeds, so it stops appearing anywhere automatically. Threat model is explicitly "keep honest people honest on a home/studio LAN, require physical device access for the bootstrap credential," not resistance to a determined attacker with sustained network access — see README's SSH section.
10. **HID device permissions — `satellite` user must be in `buttons` group.** The Buttons USB Relay udev rules own `/dev/hidraw*` as `root:buttons`. The `satellite` service user needs `usermod -aG buttons satellite` to open Stream Decks. This is done in `install-satellite.sh`. If a device was installed before this fix, run it manually once.
11. **Satellite udev rules:** Installed at `/etc/udev/rules.d/50-satellite.rules` by the official install script. They set `GROUP="satellite"` for known vendor IDs — but the Buttons rule (installed earlier) wins for Stream Decks. The group fix (gotcha #10) is the correct solution; do not delete or reorder udev rules.
12a. **The `streamdeck` PyPI library needs `libhidapi-libusb0`, not `libhidapi-hidraw0` — confirmed on real hardware (Stream Deck MK.2), corrected 2026-08-24.** Originally assumed (wrong, untested guess) that the hidraw backend was the right one since it's what the Buttons udev rule already grants. In fact `streamdeck` 0.9.8 ships exactly one transport — `StreamDeck/Transport/LibUSBHIDAPI.py` — there's no hidraw-native path in the library at all, so it hard-requires `libhidapi-libusb.so` regardless. That means it needs USB-level permissions, not hidraw permissions: a separate udev rule on `/dev/bus/usb/*` (`SUBSYSTEM=="usb", ATTR{idVendor}=="0fd9", MODE="0660", GROUP="buttons"`, in `/etc/udev/rules.d/61-dpx-deck-splash.rules`), since Buttons' own rule only covers `KERNEL=="hidraw*"`. `install-deck-splash.sh` installs the libusb variant + this rule. Lesson: don't guess a dependency's internal transport choice — the library's own source tree (or a live hardware test) settles it, an assumption doesn't.
12. **Satellite REST API on port 9999:** `http://localhost:9999/api/config` — GET returns current config; POST `{"host":"...","port":16622}` updates it live. Used by the web UI's `/satellite-config` POST handler.
13. **Companion's official installer purges `/opt/fnm`, which Satellite still depends on — install Companion BEFORE Satellite, never after.** `companion-pi`'s `update.sh` unconditionally does `rm -rf /opt/fnm` as a cleanup step ("fnm is no longer used by the modern flow"), but Satellite's systemd unit and `install-satellite.sh`/`update-satellite.sh` hard-depend on `/opt/fnm/aliases/default/bin/node`. Satellite's own installer freshly reprovisions `/opt/fnm` every time it runs, so as long as it installs *last* this is a non-issue. With the wrong order, every full-variant build shipped with Satellite silently broken from first boot (`systemd: status=203/EXEC`) — found live 2026-08-26. `dpx-buttonode.pkr.hcl` provisions Companion before Satellite for this reason; do not reorder.
14. **A missing `/dev/hidraw*` node for the Stream Deck doesn't always mean a hardware/kernel problem — try `udevadm trigger` before assuming a physical replug is needed.** Confirmed live 2026-08-26/29: after heavy mode-switch churn, the kernel can still have `hid-generic` bound to the device (visible in `dmesg`) while udev never (re)creates its `/dev/hidraw*` node — invisible to libusb-based consumers (deck-splash, Satellite) but fatal to Companion's hidraw-only surface driver. `udev_retrigger()` in `dpx-buttonode-ui.py` (`udevadm trigger --subsystem-match=hid` + `--subsystem-match=usb`) fixes this without a bus reset or physical replug in the common case, and is baked into `switch_mode()` itself now — it runs before every mode's service starts, not just when someone notices and manually hits `/power-cycle-deck`. The old disruptive `usb_power_cycle()` unbind/bind (which *did* sometimes need an actual physical replug, per the ROADMAP's -110 error history) is only reached as a fallback if the gentle trigger didn't already fix it.
15. **`/etc/dpx-mode` staying correct after a crash does not mean the mode's service is actually running — never gate a "relaunch" action purely on whether the mode string changed.** Found live 2026-08-29: after `companion.service` died (crash or a reboot following one), `/etc/dpx-mode` still correctly said `companion`, but `switch_mode(new_mode)` bailed out early with `"Already in {mode} mode"` whenever `new_mode == current`, regardless of whether the service was actually up. Both the web UI's Mode tab and the deck's GO key funnel through this same function, so there was no way to relaunch a dead-but-still-selected mode from either. Fixed by checking `svc_active(new_svc)` before treating "same mode" as "nothing to do" — the persisted string is a *record of intent*, not proof of current state.
16. **Companion's update source is a Bitfocus-hosted API, not GitHub Releases — `bitfocus/companion-pi` has zero releases of its own.** That repo is only the installer scripts (`install.sh`/`update.sh`); the actual build artifacts are served from `https://api.bitfocus.io/v1/product/companion/packages` (confirmed by reading `update-prompt/main.py`, the interactive version picker `update.sh` invokes). Querying `companion-pi`'s GitHub releases for a "latest version" always silently returns nothing — found live 2026-08-29, `_check_companion_update()` had been checking the wrong source since it was written, always showing "unknown." The real API returns entries per build `target` (e.g. `linux-arm64-tgz` for our boards) with a bare `vX.Y.Z` — compare against just the leading `X.Y.Z` of our stored version, which includes a build-hash suffix (`5.0.4+9717-stable-...`) the API's version string never matches.
17. **Real Raspberry Pi OS images are two-partition (boot + root) — the `arm-image` Packer plugin's `image_mounts` must match the source image's actual partition count exactly, or the build fails with `"error different of partitions than expected"`.** Armbian images are single-partition, so `dpx-buttonode.pkr.hcl` historically hardcoded `image_mounts = ["/"]`. That's now a variable (`var.image_mounts`, default `["/"]` for Armbian); the Raspberry Pi OS pipeline (`.github/workflows/raspios-builder.yaml`) passes `-var 'image_mounts=["/boot","/"]'`. Root-caused by reading the *actual pinned plugin version's* source (`pkg/builder/step_mount_image.go` in `packer-plugin-arm-image` v0.2.7) — don't assume the `main` branch of a pinned dependency matches; confirmed live 2026-08-29.
18. **`systemctl disable --now <svc>` inside the Packer chroot works on Armbian's older systemd but hard-fails on Raspberry Pi OS Trixie's newer systemd** (`--now cannot be used when systemd is not running... refusing`), killing the whole build with a non-`0` exit. Armbian's chroot silently no-ops `--now` there; Trixie's systemd does not. `--now` (stop) is meaningless at image-build time anyway — nothing is actually running in the chroot — so the fix is just dropping it: plain `systemctl disable <svc>` still removes the enable symlink, which is all that's needed. Confirmed live 2026-08-29, `scripts/install-satellite.sh`'s buttons-relay disable was the offender. The `ssh.socket`/`ssh.service` disables in `dpx-buttonode.pkr.hcl` were already guarded with `|| true` and are unaffected — but any *new* `--now` disable added to a provisioning script needs the same treatment (drop `--now`, or guard it) unless it's confirmed to only ever run at real boot time (not inside the chroot).
19. **`adduser --system <name>` alone does NOT create a matching same-named group — use `adduser --system --group <name>`, or a later `chown user:user ...` will fail with `invalid group`.** Without `--group`, the system user falls back to a default system group (not one named after the user) on this Debian/Raspberry Pi OS version. Confirmed live 2026-08-29 — broke `install-dashboard.sh`'s `chown -R dpx-dashboard:dpx-dashboard $DASH_HOME` at the very last step of a `full`-variant build.
20. **A kiosk/X11 systemd service running as a non-root `User=` with `TTYPath`/`StandardInput=tty` set will crash-loop on Pi 4 with `xf86OpenConsole: Cannot open virtual console 1 (Permission denied)`.** A systemd `User=` service doesn't get a real logind/PAM session for VT console access just from `TTYPath` alone — confirmed the hard way in the sibling `dpx_openPanel` project (issue #6, same Pi 4 kiosk problem). `dpx-dashboard.service` (`scripts/install-dashboard.sh`) runs as `User=root` specifically to sidestep this, with no `TTYPath`/`StandardInput=tty`/`TTYReset`/`TTYVHangup` at all — root has console access outright. Chromium/Electron under root also requires `--no-sandbox`, already present in the `.xinitrc`'s launch line. Don't "clean up" this unit back to a non-root user without re-solving this problem first.

### Common Operations

**Update Buttons to a new version:**
```bash
./scripts/upload-mirror.sh ~/Downloads/bitfocus-buttons-usb-relay-headless_X.Y.Z_arm64.tar.gz
gh workflow run release-action.yaml --repo dubpixel/dpx_buttonode
```

**Manual single-board test build:**
Go to Actions → Build Armbian + dpx-buttonode Image → Run workflow → pick board

**Force re-release of current version:**
Actions → Release — dpx-buttonode Images → Run workflow → Force: true

**Add a new board to the matrix:**
Edit `.github/workflows/release-action.yaml` under `matrix.board`, add the Armbian board ID. Also add it to the `workflow_dispatch` options in `armbian-builder.yaml`.

> Manual-only boards (not in auto-release matrix): everything else in the 150+ board `workflow_dispatch` list

> Auto-release matrix boards: `rockpi-s`, `rockpi-4b`, `rockpi-4bplus`, `rock-s0`

**Check what version is in the mirror:**
```bash
gh release view buttons-deb-mirror --repo dubpixel/dpx_buttonode --json assets --jq '.assets[].name'
```

### Skills Available

| Skill | When to invoke | What it does |
|-------|----------------|--------------|
| `screenshot-html-preview` | After editing `dpx-buttonode-ui.py` or HTML preview files | Python source → static HTML mocks → pixel-accurate screenshots in `images/` |
| `update-docs` | Bumping version, updating README, CHANGELOG, or release prep | Semver bump, changelog entry, README accuracy check, roadmap grooming |

### Reference

**Source of truth for Buttons USB Relay installation and configuration:**
https://support.bitfocus.io/hc/en-us/articles/33855997471890-Bitfocus-Buttons-USB-Relay-Raspberry-Pi

If anything about the install process, service name, config file location, or port changes — check here first before assuming the code is wrong.

This is broadcast infrastructure tooling — it runs 24/7 as a headless appliance in a production AV environment. Reliability and simplicity trump features. The image must boot clean, start the service automatically, and be discoverable via mDNS with zero configuration. Keep the build pipeline transparent and auditable: no magic, no hidden credentials, no framework abstractions that obscure what's actually happening inside the image.

---

## 0. Mid-Session Issue Triage (MANDATORY)
**Default: log it, don’t fix it mid-session.**

- If something broken or wanted comes up, file a GitHub issue and move on
- Only fix immediately if you explicitly say *“fix this”* or *“fix it now”*
- Start of session: `gh issue list --repo <owner>/<repo>`
- End of session: `gh issue create --repo <owner>/<repo> --title "..." --body "..."`

The rationale: prevents mid-session context-switching that breaks working code.

---

## 1. Automatic Workflow (MANDATORY)

These actions are **required** and must happen automatically. **NEVER ask permission** for these workflow steps.

### Branching Strategy

**BEFORE starting ANY code changes:**

1. Create a new branch from the default branch (master/main)
2. Never work directly on default branch
3. Branch naming conventions:

| Type | Format | Example |
|------|--------|---------|
| New feature | `feature/brief-description` | `feature/mqtt-decoder` |
| Bug fix | `fix/issue-description` | `fix/telegraf-timeout` |
| Documentation | `docs/what-changed` | `docs/update-architecture` |
| Refactor | `refactor/component-name` | `refactor/docker-volumes` |

### Version Bumping

**BEFORE the first code change:**

Bump the version number according to semantic versioning:

| Change Type | Version Bump | Example |
|-------------|--------------|---------|
| Bug fix, typo fix, documentation update | Patch (0.0.X) | 1.2.3 → 1.2.4 |
| New feature, new endpoint, new capability | Minor (0.X.0) | 1.2.3 → 1.3.0 |
| Breaking change, API removal, incompatible change | Major (X.0.0) | 1.2.3 → 2.0.0 |

#### Semantic Versioning Principles

**Format:** `MAJOR.MINOR.PATCH` (e.g., `2.4.7`)

- **MAJOR**: Incompatible API changes, breaking existing functionality
- **MINOR**: New functionality added in a backwards-compatible manner  
- **PATCH**: Backwards-compatible bug fixes, docs, typos

**Pre-1.0 versions (0.x.y):**
- Anything goes - breaking changes allowed in minor bumps
- Common for projects in initial development
- Move to 1.0.0 when API is stable and production-ready

**Pre-release versions:**
- Alpha: `1.0.0-alpha.1` (early testing, unstable)
- Beta: `1.0.0-beta.2` (feature-complete, testing for bugs)
- Release Candidate: `1.0.0-rc.1` (final testing before release)

#### Version Bumping Decision Tree

**When multiple changes occur, use the highest level:**
- Bug fix + new feature → Minor bump (not patch)
- New feature + breaking change → Major bump (not minor)

**Edge cases:**

| Scenario | Bump Type | Reasoning |
|----------|-----------|-----------|
| Internal refactor, no API change | Patch | No external impact |
| New optional parameter with default | Minor | Backwards-compatible addition |
| Changed parameter order | Major | Breaks existing calls |
| Deprecated feature (still works) | Minor | Deprecation warning added |
| Removed deprecated feature | Major | Functionality removed |
| Performance improvement | Patch | Implementation detail |
| New dependency added | Minor | Expands capabilities |
| Security fix | Patch | Even if behavior changes slightly |
| Database schema change | Major | Requires migration |
| Config file format change | Major | Breaking existing configs |

#### Version Bump Workflow

1. **Determine bump type** based on changes planned
2. **Update version number** in code/config files
3. **Create git commit**: `bump version to X.Y.Z`
4. **Tag the commit**: `git tag vX.Y.Z` (note the `v` prefix)
5. **Push with tags**: `git push && git push --tags`
6. **Update CHANGELOG** (if present) with version and changes
7. **Proceed with feature/fix implementation**

**Version commit should be standalone** - don't mix version bump with other changes.

#### Changelog Integration

If project has CHANGELOG.md, update it with version bump:

```markdown
## [1.2.0] - 2026-02-13

### Added
- New feature description

### Fixed
- Bug fix description

### Changed
- Breaking change description
```
**If no CHANGELOG.MD file exists:** Create one in the root of the project.

**Where to bump version:**
- Python: `__version__` in `__init__.py` or `pyproject.toml`
- Node.js: `version` field in `package.json`
- General: `VERSION` file or constant in main entry point
- Docker: Version tag in `docker-compose.yml` or `Dockerfile` labels

**If no version file exists:** Create one in an appropriate location for the project.

### Version File Standards & Location

To ensure consistent version identification across projects, follow these standards:

#### Python Projects

**Preferred location: `app/__init__.py` or `src/__init__.py`**

```python
"""Project description."""

__version__ = "1.0.0"
__author__ = "dubpixel"
```

**Alternative: `pyproject.toml` (for modern Python packaging)**

```toml
[project]
name = "project-name"
version = "1.0.0"
```

**Alternative: `VERSION` file in project root**

```
1.0.0
```

Then read it in your module:
```python
from pathlib import Path
__version__ = (Path(__file__).parent / "VERSION").read_text().strip()
```

#### Node.js/JavaScript Projects

**Location: `package.json`** (standard)

```json
{
  "name": "project-name",
  "version": "1.0.0",
  "description": "Project description"
}
```

#### Docker Projects

**Location: `docker-compose.yml` labels AND `Dockerfile`**

`docker-compose.yml`:
```yaml
services:
  app:
    build: .
    labels:
      - "org.opencontainers.image.version=1.0.0"
      - "org.opencontainers.image.created=${BUILD_DATE}"
```

`Dockerfile`:
```dockerfile
LABEL org.opencontainers.image.version="1.0.0"
LABEL org.opencontainers.image.title="Project Name"
```

#### Bash Scripts/Utilities

**Location: Top of main script or separate `VERSION` file**

```bash
#!/bin/bash
VERSION="1.0.0"
SCRIPT_NAME="manage.sh"

# Or read from VERSION file:
# VERSION=$(cat VERSION)
```

#### Version Display (REQUIRED)

**Always provide a way to display the version:**

- Python CLI: `python -m myapp --version`
- Node.js: `npm run version` or built into CLI
- Docker: `docker inspect <image> | grep version`
- Bash: `./script.sh --version`

**Example implementations:**

```python
# In your main.py or CLI entry point
import argparse
from app import __version__

parser = argparse.ArgumentParser()
parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
```

```bash
# In bash script
if [[ "$1" == "--version" ]] || [[ "$1" == "-v" ]]; then
    echo "$SCRIPT_NAME version $VERSION"
    exit 0
fi
```

#### Multi-Component Projects

For projects with multiple components (e.g., frontend + backend + Docker):

1. **Synchronized versioning**: All components share the same version
2. **Central `VERSION` file** in project root
3. **Scripts/tools read from central file**

Example structure:
```
project-root/
├── VERSION              # 1.0.0
├── backend/
│   └── __init__.py      # Reads ../VERSION
├── frontend/
│   └── package.json     # Reads ../VERSION via build script
└── docker-compose.yml   # Reads VERSION via envsubst or build args
```

### Pull Request Creation

**AFTER completing the task:**

Create a pull request with this format:

```markdown
## Changes
- [Brief list of what changed]
- [One item per significant change]

## Testing
- [How to verify the changes work]
- [Commands to run or steps to follow]

## User Prompt
[The original request from the user - verbatim]
```

**PR Title Format:** `[Component] Brief description`

Examples:
- `[MQTT] Add BLE decoder support`
- `[Docs] Consolidate architecture documentation`
- `[Telegraf] Fix enum processor deprecation`

**NEVER ask permission to create the PR - just do it.**

### Build Artifact Naming

Non-`main` builds append the branch slug to the filename so artifacts are
self-identifying without opening the run log.

| Branch | Filename |
|--------|----------|
| `main` | `<name>-vX.Y.Z.<ext>` |
| anything else | `<name>-vX.Y.Z-<branch-slug>.<ext>` |

```bash
if [ "$BRANCH" = "main" ]; then
  OUT="myapp-v${VERSION}.ext"
else
  BRANCH_SLUG=$(echo "$BRANCH" | sed 's|/|-|g' | sed 's|[^a-zA-Z0-9._-]|-|g')
  OUT="myapp-v${VERSION}-${BRANCH_SLUG}.ext"
fi
```

---

## 2. Progress Tracking for Multi-Step Work

When working on tasks that span **more than 3 files** OR **more than 30 minutes of work**:

### Checkpoint Progress

Provide a status update using this template:

```markdown
## Progress Checkpoint

✅ **Completed:**
- Item 1 description
- Item 2 description

⬜ **Remaining:**
- Item 3 description
- Item 4 description

→ **Next Action:** [Specific next step you will take]
```

### When to Checkpoint

- After completing a logical phase of work
- Before switching to a different component
- When encountering a blocker or decision point
- Every 3-5 file edits in large refactors

### Resuming from Checkpoint

When continuing work after a checkpoint:
1. Read the last checkpoint status
2. Start with the "Next Action" item
3. Update checkpoint when that phase completes

**Purpose:** Prevents agents from getting lost in complex multi-step tasks and provides visibility to the user.

---

## 3. File Header Standards

All code files must include a comprehensive header comment section:

```
# ================================================================================
# [FILE TYPE] - [FILE PURPOSE]
# ================================================================================
# you can maybe write some stuff here - tagline etc.
# ================================================================================
# PROJECT: [project_name]
# ================================================================================
#
# File: [filename]
# Purpose: [what this file does]
# Dependencies: [key dependencies if any]
#
# CHANGE LOG: (if needed but should really be in the changelog for the git)
# 
# 2026-03-06: Complete rewrite - Interactive wizard (v2.1.0)
#
# ================================================================================
```

### Header Guidelines

- Use consistent separator lines (80 characters of `=`)
- Adjust comment syntax for the language (`#` for Python/bash, `//` for JS/C++, etc.)


---

## 4. Documentation Standards

### Project Context Documentation

Project-specific architecture, decisions, and operational knowledge should live in the **PROJECT section at the top of this file**. This keeps rules and context unified in one scannable document.

**When to use a separate CONTEXT.md:**
Only create a separate `CONTEXT.md` if reference data becomes large enough to be noisy:
- Long IP/VLAN tables
- Full API response examples  
- Hardware pinout references
- Extensive data schemas

If you create CONTEXT.md for overflow, add a reference in the PROJECT section at the top: "See CONTEXT.md for full network topology."

### How to Document Project Context

**DO:**
- ✅ Keep it clean, factual, and scannable
- ✅ Update when architecture changes
- ✅ Add information when you learn important project details
- ✅ Use tables, code blocks, and clear headings
- ✅ Think: "What does the next agent need to know?"
- ✅ Write in present tense, authoritative voice

**DON'T:**
- ❌ Append conversation transcripts
- ❌ Include timestamps like "On Feb 12 we discussed..."
- ❌ Make it a session log or diary
- ❌ Duplicate content from README.md (link instead)
- ❌ Let it become verbose or messy

**Update frequency:** Whenever you make architectural changes or learn critical project information.

---

## 5. Core Principles


### No Modifications to Working Code

- Do not refactor, optimize, or "improve" code that is working unless explicitly requested
- Avoid drive-by refactors when implementing a feature
- If you see potential improvements, mention them but don't implement without approval

### Comprehensive Commenting

- Document all code with clear, meaningful comments
- Preserve existing comments unless they become obsolete
- Remove or update comments that are no longer accurate
- Document WHY, not just WHAT (the code shows what, comments explain why)

### Small, Incremental Changes

- Make one logical change per commit
- Break large tasks into smaller steps
- Test each change before moving to the next
- Make it easy to review and roll back if needed

### Stay Focused

- Complete the current task before suggesting next steps
- Answer only what is asked
- Don't anticipate or propose additional work unless requested

### Document Everything

- README.md must be updated and maintaned when appropriate as per these guidelines
- CONTEXT.md must be updated and maintaned when appropriate as per these guidelines
- a comprehensive CHANGELOG.md must be kept updated and maintaned when appropriate as per these guidelines
- you can maintain a small changelog in the header if you wish but main changelog should be in the MD

---

## 6. Documentation Standards

### Inline Documentation

- Maintain comprehensive inline documentation
- Update comments when code changes (keep them in sync)
- Document all function parameters and return values
- Include usage examples for complex functions
- Explain algorithms and business logic


### README Files

- Keep README.md current and accurate
- README is user-facing - focus on how to USE the project
- **Confirm all changes to README with the user before committing**
- README should not duplicate CONTEXT.md (different audiences)

### CHANGELOG.MD

- Keep CHANGELOG.md current and accurate
- CHANGELOG is user-facing - focus on changes, version numbers, dates and git hashes if needed
- **keep this automated in background**
- changelog could be retroactively updated to reflect git commit names if that adds clariy
- **any changes to existing changelog line items should be confirmed with user**

### Markdown Style

- Use consistent heading hierarchy (don't skip levels)
- Use tables for structured information
- Include code blocks with language tags
- Use relative links to other project files
- Keep line length reasonable (~80-100 chars for prose)

---

## 7. Code Quality Guidelines

### General Principles

- Write clear, readable code with meaningful names
- Follow established coding patterns within the project
- Implement proper error handling (don't use bare `except:` or `catch`)
- Write testable code with clear interfaces
- Maintain consistent formatting and style

### Language-Specific

Agents should infer and follow the conventions of the language they're working in:
- Python: Follow PEP 8
- JavaScript: Follow project's ESLint config if present
- Bash: Follow Google Shell Style Guide principles
- Other languages: Use community-standard style guides

### Testing

- Add tests alongside new logic when appropriate
- Use deterministic inputs for tests (inject time/randomness, don't read system state)
- Name tests by behavior (e.g., `test_early_finish_extends_break`)
- Include both positive and negative test cases
- if the process includes: using ssh into a remote server, or user input in any way. open a terminal first for the user so you both can read it. 

---

## 8. Change Management

### Commit Practices

- **Commit message format:** Short, plain English, lowercase verb
  - Examples: `add mqtt decoder`, `fix telegraf config`, `update documentation`
- Make one logical change per commit
- Commit functional units (don't commit broken code)

### Before Committing

- Verify the code works (run/test it)
- Update all relevant documentation
- Update file change logs
- Remove debug code and console.log/print statements
- Check that no credentials or secrets are included

### After Committing

- Push to the feature branch
- Create PR (as described in Section 1)
- Include verification steps in PR description

---

## 9. Collaboration Standards

### Respect Existing Architecture

- Understand existing architectural decisions before changing them
- Ask for clarification when requirements are ambiguous
- Suggest alternatives when appropriate, but don't insist
- Consider the impact of changes on the broader codebase

### Maintain Backwards Compatibility

- Don't break existing APIs unless explicitly requested
- Provide migration paths for breaking changes
- Document any compatibility changes in PR description

### Communication

- Explain the reasoning behind suggested changes
- Provide rollback information when making significant changes
- Be transparent about limitations or uncertainties
- Keep responses concise and focused

---

## 10. Configuration & Secrets

### Environment Variables

- Use `.env` files for local development
- Provide `.env.example` with all required variables (use placeholder values)
- **NEVER commit** `.env` files or actual credentials to git
- Document all environment variables in CONTEXT.md or README.md

### Sensitive Data

- Keep credentials in environment variables, not hardcoded
- Use service account files in standard locations (e.g., `~/.config/gcloud/`)
- Add sensitive files to `.gitignore` immediately
- If secrets are accidentally committed, notify the user immediately

---

## Summary: Agent Checklist

Before starting work:
- [ ] Create feature branch
- [ ] Bump version appropriately

While working:
- [ ] Follow file header standards
- [ ] Update change logs in modified files
- [ ] Keep changes small and focused
- [ ] Checkpoint progress if task is large
- [ ] Update PROJECT section if architecture changes

After completing work:
- [ ] Test/verify the changes
- [ ] Update relevant documentation
- [ ] Create PR with proper format
- [ ] No credentials committed

---

*These standards ensure consistent, high-quality AI assistance across all Dubpixel projects.*
