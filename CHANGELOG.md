# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

---

## [0.7.0] - 2026-08-29

Deck redesign, SSH security overhaul, on-device auto-updates, and a first real
fresh-flash hardware validation pass — including several real bugs that pass
only surfaced, none of which a successful build would have caught.

### Added
- **Deck splash Phase 2/3, hardware-validated:** the boot splash grew into a
  full stage-then-GO config screen. MODE key cycles Buttons → Satellite →
  Companion (color-coded, skips Companion if not installed); NET toggles
  staged DHCP ↔ static; SUBNET cycles `/24 /22 /16 /8`; holding an octet key
  spins its value (locked unless NET is staged to static); GO commits mode +
  network together as one combined operation. Reached via a narrowly-scoped
  `/etc/sudoers.d/dpx-splash` rule (`--apply-mode <value>`/`--toggle-net`/
  `--pin-static <ip>[/prefix]`) — `dpx-deck-splash.py` itself stays
  unprivileged (`buttons` group only) throughout.
- **SSH security overhaul:** SSH ships fully disabled by default (no
  hardcoded credential at all). `dpx-init-ssh.service` generates a random
  root password once, on first boot, written group-readable to
  `/etc/dpx-initial-ssh-password`. The password is **never shown on the web
  UI** — the only place it's ever revealed is a dedicated key on the deck,
  which requires a real press of a physical key to reveal (originally
  hold-to-reveal; changed to press-to-toggle after hardware testing showed
  a finger covering the key also covered the text it was revealing). The
  web UI's new SSH tab gates every action (enable/disable/change password)
  behind the current root password, since the page itself has no login of
  its own.
- **On-device auto-update system:** new Updates tab checks all four
  components (dpx-buttonode software, Buttons, Satellite, Companion)
  against their real upstream sources and applies updates in place.
  `dpx-buttonode-ui.py`/`dpx-deck-splash.py` self-update with a
  validate-then-atomic-swap and a boot-attempt counter that auto-restores
  the last backup if a bad update crash-loops the service. Buttons updates
  via the mirrored `.deb`. Satellite/Companion update via new slim
  `scripts/update-satellite.sh`/`update-companion.sh` (not the install
  scripts, which force-switch the active mode) run as detached background
  jobs with progress the Updates tab polls.
- **Docker test infrastructure** (`test/docker/`): Companion and Buttons
  containers deployable to a shared dev droplet, isolated from other
  projects on the same box. Lets Satellite mode be tested against a real
  Companion instance without a second physical unit or a full-variant
  build; the Buttons container regression-tests the `.deb` install/update
  mechanism (not real HID behavior, which needs actual hardware).
- `FIRST-BOOT-TEST-PLAN.md` — a running checklist of everything that needs
  re-verifying on a genuinely blank flash, since day-to-day iteration
  happens on one hand-patched unit whose first-boot-only logic never gets
  naturally re-exercised.
- `update-docs` skill (`.github/skills/update-docs/SKILL.md`) — full
  documentation audit workflow for dpx_buttonode
- README: hardware photo, UI screenshots grid, screenshots quick link

### Changed
- **Project renamed `buttnode` → `buttonode`** (repo, package, filenames,
  docs, CI, GitHub repo/remote).
- **Default operating mode flipped from Buttons to Companion Satellite** —
  most units are meant to sit in a Companion-driven setup out of the box.
- **Companion now installs before Satellite** in the Packer build (was the
  reverse) — see Fixed.
- Deck splash: IP display now shows the web UI port (`:8080`) as a 5th key
  alongside the 4 octets, when the deck has room.

### Fixed
- **SSH wasn't actually disabled.** Found live on a genuinely fresh flash:
  disabling only `ssh.service` left SSH fully reachable the entire time,
  because Ubuntu ships `ssh.socket` enabled alongside it — socket
  activation means systemd listens on `:22` and lazily starts `ssh.service`
  on the first connection attempt regardless of the service's own state.
  `systemctl is-enabled ssh` said "disabled" throughout; it was never true.
  Same gap existed in the web UI's SSH tab toggle. Fixed in both the
  Packer provisioning and `dpx-buttonode-ui.py`.
- **Companion silently broke Satellite on every full-variant build.**
  `companion-pi`'s official installer unconditionally purges the shared
  `/opt/fnm` Node runtime as a cleanup step, but Satellite's systemd unit
  still depends on it — and Satellite installed *before* Companion in the
  old provisioning order, so Companion's install always wiped out what
  Satellite had just set up. Fixed by swapping the install order.
- **GO silently did nothing if the selected mode's service had already
  died.** `/etc/dpx-mode` staying e.g. `companion` after a crash doesn't
  mean `companion.service` is actually running, but the mode-switch logic
  only checked whether the *string* had changed — found live after a
  crash left the persisted mode unchanged but the service dead, with no
  way to relaunch it from the web UI or the deck. Fixed at the source
  (`switch_mode()`), so it now also checks whether the service is
  actually active.
- **Stream Deck `/dev/hidraw*` node going missing after mode-switch
  churn** — invisible to libusb-based consumers (Satellite, the deck
  splash itself) but fatal to Companion's hidraw-only surface driver.
  Fixed with a gentle `udevadm trigger` step, tried before the disruptive
  unbind/bind fallback (which previously needed a physical replug in some
  cases) — now baked into every mode switch automatically, not just
  triggered manually after the fact.
- **Companion's update check queried a repo with zero releases,** always
  silently reporting "unknown." Companion's real release source is a
  Bitfocus-hosted API, not GitHub Releases — `bitfocus/companion-pi` (the
  repo `install-companion.sh` downloads its *installer* from) has never
  published a GitHub release itself.
- `dpx-init-ssh.sh` SIGPIPE-under-`pipefail` crash and a `tr` locale bug
  that could corrupt the generated password.
- Deck splash Phase 1 (boot-window IP/hostname display) required two
  earlier live fixes not caught by CI: the `streamdeck` library needs
  `libhidapi-libusb0` + a `/dev/bus/usb/*` udev rule, not
  `libhidapi-hidraw0` as originally assumed (no hidraw transport exists
  at all); hostname now chunks onto keys on word boundaries
  (`dpx`/`buttonode`/`2199`/`local`) instead of a fixed-length slice that
  broke words mid-word.

---

## [0.6.0] - 2026-07-28

### Added
- **Full image variant:** `full` builds include Bitfocus Companion (full) in addition to Buttons USB Relay
  and Companion Satellite. `lite` builds are the existing behaviour (Buttons + Satellite only).
- **`scripts/install-companion.sh`:** installs full Bitfocus Companion via official `companion-pi/install.sh`
  (pre-built arm64 binary, no compile step, ~15-25 min). Adds `companion` user to `buttons` group for HID
  access. Appends `COMPANION_VERSION` and `VARIANT=full` to `/etc/dpx-buttonode-release`.
- **`variant` Packer variable:** `lite` (5 GB image) or `full` (8 GB image). Ternary expression controls
  `target_image_size`. `VARIANT` written to `/etc/dpx-buttonode-release` on all builds.
- **`variant` workflow input:** `armbian-builder.yaml` exposes `variant: lite|full` on both
  `workflow_dispatch` and `workflow_call`. Passed to Packer.
- **Variant in artifact name:** `{board}-dpx-buttonode-{ver}-{variant}-{commit}.img.gz`
- **Release matrix expanded:** `release-action.yaml` builds both `lite` and `full` per board (4 artifacts for
  2-board matrix).
- **Companion mode in UI:** Mode tab now shows three buttons — Buttons / Satellite / Companion.
  Companion button is disabled on Lite images (graceful degradation, detected via `/opt/companion` presence).
  Mode card on Status page handles `companion` mode (amber colour, direct link to port 8000).
- **Build info footer shows variant:** `dpx-buttonode v0.6.0 [full]` — companion version included when
  `variant=full`.

### Changed
- `/etc/dpx-mode` now accepts `buttons`, `satellite`, or `companion`
- POST `/mode` handler updated to map all three modes to their respective systemd service names

---

## [0.5.0] - 2026-07-17

### Added
- **Project rename:** `dpx_buttons_relay_armbian` → **`dpx-buttonode`** — repo name, artifact names,
  release tags, workflow names, and all OUR identifiers updated. Bitfocus package names unchanged.
- **`dpx-node-ui` → `dpx-buttonode-ui`:** service, binary path, web page title, and avahi XML
  file renamed. mDNS service type `_dpx-buttonode._tcp` unchanged.
- **Companion Satellite A/B mode:** Companion Satellite (headless) is now installed alongside
  Buttons USB Relay. Both are installed at image build time; only one runs at a time.
  - Default mode on first flash: **Buttons USB Relay** (satellite installed but disabled)
  - `scripts/install-satellite.sh` — installs Companion Satellite using the official install
    script (`pi-image/install.sh`) inside the Packer chroot; leaves `satellite.service` disabled;
    adds `satellite` user to `buttons` group for HID device access (Stream Deck udev fix)
  - `dpx-buttonode.pkr.hcl` — two new provisioners: copy + run `install-satellite.sh`
  - Mode persistence: `/etc/dpx-mode` stores `buttons` or `satellite` across reboots
  - Mode switching via `systemctl enable/disable` on each service
- **Mode tab in `dpx-buttonode-ui`:** new "Mode" tab in the web UI for A/B switching
  - Large mode badge (BUTTONS / SATELLITE) with colour coding
  - Service status for the active service
  - Switch button: stops+disables current service, enables+starts the other
  - Companion server config form: Host + Port (default 16622), saved to
    `/etc/dpx-satellite.conf` and `/boot/satellite-config`; POSTs to satellite REST API
    (`http://localhost:9999/api/config`) if satellite is currently running
- **Mode status card on Status page:** Status tab now shows current mode (BUTTONS/SATELLITE),
  active service status, and (in satellite mode) the configured Companion host:port
- **HID device permission fix:** `satellite` user added to `buttons` group at build time so
  Stream Decks are accessible when in satellite mode (udev owns `/dev/hidraw*` as `root:buttons`)
- **Comprehensive README:** added Satellite mode usage section, Mode tab screenshots, terminal
  mode-switch commands, Companion configuration instructions
- **Favicon:** `images/fav_icon.png` served at `/favicon.png` and `/favicon.ico` on port 8080;
  provisioned into image via Packer; installed to `/usr/local/bin/fav_icon.png`
- **Build metadata baked into image:** Packer writes `/etc/dpx-buttonode-release` containing
  `DPX_VERSION`, `BUTTONS_VERSION`, `SATELLITE_VERSION`, `GIT_BRANCH`, `GIT_COMMIT`, `BUILD_DATE`;
  `install-satellite.sh` appends `SATELLITE_VERSION` after build
- **Build info footer in web UI:** every page shows a slim footer bar:
  `dpx-buttonode v{ver} · buttons {ver} · satellite {ver} · {branch}@{commit} · built {date}`
- **Build info in release notes:** GitHub Release body includes a versions table
  (dpx-buttonode, Buttons, Satellite, branch@commit)

### Changed
- Artifact filename format: `{board}-dpx-buttonode-{dpx_version}-{branch}-{commit}.img.gz`
  (branch + commit SHA appended; Buttons version removed from filename — it's in the UI footer and release notes)
- Release title format: `dpx-buttonode v{dpx_version} — Buttons {buttons_version}`
  (was `dpx-buttonode {buttons_version} (build {dpx_version})`)
- Satellite `package.json` path corrected to `/opt/companion-satellite/satellite/package.json`

---

## [0.4.0] - 2026-07-16

### Added
- **Dynamic hostname:** `dpx-set-hostname.service` sets hostname to `dpx-buttonode-XXXX` (last 4 hex
  chars of primary Ethernet MAC, uppercase) on first boot. Reads MAC from `/sys/class/net/<iface>/type`
  (kernel sysfs, available before network stack starts). Ordered `Before=network.target avahi-daemon.service`
  so avahi reads the correct hostname on first start.
- **`dpx-buttonode-ui` web UI** on port 8080 — pure Python 3 stdlib, zero extra packages.
  Tabs: Status, Hostname, Network, Devices, Nodes.
  - **Hostname:** `hostnamectl` + `/etc/hosts` + avahi reload
  - **Network:** DHCP ↔ static. Works on Armbian with Netplan + systemd-networkd.
    Writes `/etc/systemd/network/09-dpx-<iface>.network` (sorts before Netplan's `10-` wildcard),
    deletes the conflicting `/run/systemd/network/10-netplan-all-eth-interfaces.network`,
    then restarts networkd — the only approach that reliably beats Netplan's DHCP wildcard.
  - **Devices:** USB device list, Stream Deck USB power cycle (unbind/rebind port), Buttons service restart
  - **Nodes:** `avahi-browse _dpx-buttonode._tcp` discovers all other buttonodes on the LAN with links to their UIs
- `avahi-daemon.service` drop-in: `After=network-online.target` so mDNS announces on the correct IP after boot
- `_dpx-buttonode._tcp` mDNS service registration so all units appear in the Nodes tab

### Fixed
- Previous dynamic hostname (`41f433a`) used `After=network-pre.target` + fragile awk — replaced
- `netplan apply` silently returns rc=1 and deletes override files on this Armbian build — bypassed
  entirely by writing directly to `/etc/systemd/network/` and restarting networkd
- Armbian Netplan wildcard `e*` DHCP config alphabetically beats explicit `end0` static config —
  fixed by using `09-` prefix (sorts before Netplan's `10-`) and removing the `/run/` wildcard

---

## [0.3.0] - 2026-07-15

### Added
- Dynamic hostname at first boot: `dpx-buttonode-XXXX` derived from last 4 hex chars of MAC address
- `dpx-set-hostname.service` systemd oneshot service handles hostname assignment
- Secure root password baked in via `ROOT_PASSWORD` GitHub Secret (never in code)
- `ROOT_PASSWORD` secret properly chained through `workflow_call` to Packer build
- `custom-board` free-text input on `armbian-builder.yaml` — build any board not in dropdown
- `publish-release.yaml` workflow — re-publish a release from existing build artifacts without recompiling
- Release tags now include pipeline version: `dpx-buttonode-X.Y.Z-buildA.B.C`
- `force=true` on release workflow deletes and recreates the same tag; normal runs never overwrite
- Orange Pi Zero 3 added to release matrix
- Full 150+ Armbian board list in manual dispatch dropdown

### Fixed
- Removed all IPv6 disable config (`armbianEnv.txt`, sysctl, NetworkManager) — was breaking DHCP
- Self-referencing board resolve step removed; board now resolved inline in each step
- `PACKER_GITHUB_API_TOKEN` passed to `packer init` to avoid GitHub API rate limit
- `sudo` removed from `compile.sh` call (Armbian rejects being run as root)
- All post-Packer file ops use `sudo`; final `.gz` gets `chown runner:runner` for artifact upload
- YAML heredoc inside `run:` block extracted to `scripts/generate-release-notes.sh`
- Release options array syntax fixed for GitHub Actions `workflow_dispatch`

## [0.2.0] - 2026-07-15

### Added
- SSH enabled by default in image (`root` / `1234`) — no serial cable needed for debugging
- IPv6 disabled system-wide via sysctl; NetworkManager forced to IPv4 DHCP only
- `scripts/generate-release-notes.sh` — extracted from workflow to fix YAML heredoc parse error
- `scripts/upload-mirror.sh` — one-command helper to push new Bitfocus packages to mirror release
- Full 150+ Armbian board list in `workflow_dispatch` dropdown
- Rock Pi S (`rockpi-s`) corrected from wrong ID `rockpis`

### Fixed
- YAML syntax errors in `release-action.yaml` (inline array options, heredoc inside block scalar)
- `sudo mv` / `sudo gzip` / `sudo chown` for root-owned Armbian and Packer build outputs
- Release job now deletes existing tag before recreating (handles force rebuilds cleanly)
- Auto-release matrix switched from Orange Pi Zero to Rock Pi (`rockpi-s`, `rockpi-4b`, `rockpi-4bplus`, `rock-s0`)

## [0.1.0] - 2026-07-15

### Added
- Automated two-stage build pipeline: Armbian base image + HashiCorp Packer chroot customization
- Self-hosted package mirror via GitHub Releases (`buttons-deb-mirror` tag) — no Bitfocus credentials needed in CI
- Matrix builds for Orange Pi Zero family (`orangepizero`, `orangepizero2`, `orangepizero2w`, `orangepizero3`)
- Daily scheduled version check — auto-builds and publishes a GitHub Release when mirror is updated
- `scripts/upload-mirror.sh` — one-command helper to upload new Bitfocus packages to the mirror release
- `scripts/download-buttons.sh` — downloads package from mirror release using built-in `GITHUB_TOKEN`
- `scripts/install-buttons.sh` — installs `.deb` inside Armbian chroot, enables `avahi-daemon` for mDNS discovery
- `dpx-buttonode.pkr.hcl` — Packer build definition targeting ARM64 Armbian images
- Initial support for Bitfocus Buttons USB Relay Headless v0.1.0-beta.4

---

## Version Guidelines

### Semantic Versioning (MAJOR.MINOR.PATCH)

- **MAJOR**: Breaking changes, incompatible API modifications
- **MINOR**: New features, backwards-compatible additions
- **PATCH**: Bug fixes, documentation updates, typos

### Change Categories

- **Added**: New features or capabilities
- **Changed**: Changes to existing functionality
- **Deprecated**: Features marked for future removal (still working)
- **Removed**: Removed features or functionality
- **Fixed**: Bug fixes
- **Security**: Security patches or vulnerability fixes

### Example Entry Format

```markdown
## [1.2.0] - 2026-03-15

### Added
- New authentication system with JWT tokens
- Export functionality for CSV and JSON formats
- Dark mode toggle in user preferences

### Changed
- Improved database query performance by 40%
- Updated UI library from v2.1 to v3.0

### Fixed
- Fixed memory leak in background worker process
- Corrected timezone handling in date picker component

### Security
- Patched XSS vulnerability in user input validation
```

### Version Comparison Links

Add these at the bottom of the file (replace with your repo owner/name):

```markdown
[Unreleased]: https://github.com/owner/repo/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/owner/repo/releases/tag/v0.1.0
```

---

## Tips for Maintaining This Changelog

1. **Update as you work**: Add entries when making changes, not at release time
2. **Keep it scannable**: Use clear, concise descriptions
3. **Link to issues/PRs**: Include `(#123)` references when relevant
4. **Date format**: Use ISO 8601 (YYYY-MM-DD)
5. **Group by type**: Keep all Added items together, all Fixed items together, etc.
6. **User perspective**: Write what changed for users, not implementation details
7. **Unreleased section**: Keep active changes here, move to version section on release
