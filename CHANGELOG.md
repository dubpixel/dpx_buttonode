# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **Project renamed `buttnode` → `buttonode`** (repo, package, filenames, docs, CI). Full spelling reads
  cleaner and avoids the Bluetooth ("BT node") misread. GitHub repo rename + remote URL update pending as a
  separate step.

### Added
- `update-docs` skill (`.github/skills/update-docs/SKILL.md`) — full documentation audit workflow for dpx_buttonode
- README: `images/front.png` hardware photo added between hero section and TOC
- README: UI screenshots grid (`001–006_*.jpe`) replacing placeholder image paths in Usage section
- README: 📸 Screenshots quick link added next to 3D Case link in hero
- README: `#dpx-buttonode-ui` section promoted to top-level heading so TOC and Screenshots link anchor correctly
- README: satisfied `<!--todo-->` comments removed
- AGENTS.md: `html/` folder added to architecture table for UI preview pages
- ROADMAP.md: checkboxes added to planned items; Nodes tab marked as shipped
- `src/dpx-deck-splash/dpx-deck-splash.py` + `scripts/install-deck-splash.sh` (Phase 1) — draws IP + mDNS
  hostname on the Stream Deck's keys during the boot window before Buttons/Satellite/Companion claims the
  device. New low-priv `dpx-splash` user, own venv (`streamdeck` + Pillow), `dpx-deck-splash.service` with
  `Conflicts=bitfocus-buttons-usb-relay.service` for a clean device hand-off. Read-only display only — no
  keypress handling yet (Phase 2/3 planned: deck-triggered mode switch, DHCP/static toggle)
- `dpx-buttonode-ui.py`: extracted `switch_mode()` out of the inline `/mode` POST handler; added
  `--apply-mode`/`--apply-net` CLI subcommands (groundwork for Phase 2/3 above, no new privilege surface yet)

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
