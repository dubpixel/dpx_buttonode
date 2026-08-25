<!-- Improved compatibility of back to top link: See: https://github.com/othneildrew/Best-README-Template/pull/73 -->
<a id="readme-top"></a>

<!--  *** Thanks for checking out the Best-README-Template. If you have a suggestion that would make this better, please fork the repo and create a pull request or simply open an issue with the tag "enhancement". Don't forget to give the project a star! Thanks again! Now go create something AMAZING! :D -->



<!-- /// d   u   b   p   i   x   e   l  ---  f   o   r   k   ////--v0.5.7 -->
<!--this has additionally been modifed by @dubpixel for hardware use -->
<!--search dpx-buttonode.. search & replace is COMMAND OPTION F -->

<!--this is the version for software -->
<!--igure out how to get the details tag to properly render in jekyll for gihub pages.-->



<!-- PROJECT SHIELDS -->
<!--
*** I'm using markdown "reference style" links for readability.
*** Reference links are enclosed in brackets [ ] instead of parentheses ( ).
*** See the bottom of this document for the declaration of the reference variables
*** for contributors-url, forks-url, etc. This is an optional, concise syntax you may use.
*** https://www.markdownguide.org/basic-syntax/#reference-style-links
***
-->
<div align="center">

[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![License][license-shield]][license-url]
[![LinkedIn][linkedin-shield]][linkedin-url]
[![Latest Release](https://img.shields.io/github/v/release/dubpixel/dpx_buttonode?label=dpx-buttonode&color=blue&style=flat-square)](https://github.com/dubpixel/dpx_buttonode/releases/latest)
</div>
<!-- PROJECT LOGO -->
<div align="center">
  <a href="https://github.com/dubpixel/dpx_buttonode">
    <img src="images/logo.png" alt="Logo" height="120">
  </a>
<h1 align="center">dpx-buttonode</h1>
<h3 align="center"><i>Flash-ready Armbian images for <a href="https://bitfocus.io/companion">Bitfocus Companion</a> — turn any ARM SBC into a <a href="https://github.com/bitfocus/companion-satellite">Companion Satellite</a> node (or run full Companion itself), switchable at runtime</i></h3>
  <p align="center">
    Automated GitHub Actions build pipeline that produces ready-to-flash <code>.img.gz</code> images
    for ARM single-board computers (Rock Pi S, Orange Pi Zero, etc.) that boot straight into
    <a href="https://github.com/bitfocus/companion-satellite">Bitfocus Companion Satellite</a> —
    or, on the Full image variant, run full <a href="https://bitfocus.io/companion">Bitfocus Companion</a> itself.
    <a href="https://bitfocus.io/buttons">Bitfocus Buttons USB Relay</a> is also supported as a third mode.
    Switch between modes from the browser — no re-flash needed.
    Write the image, plug in your Stream Deck, power on — done.
    <br /><br />
     »  
     <a href="https://github.com/dubpixel/dpx_buttonode/releases"><strong>Download a Release »</strong></a>
     <br />
    <a href="https://github.com/dubpixel/dpx_buttonode/issues/new?labels=bug&template=bug-report---.md">Report Bug</a>
    ·
    <a href="https://github.com/dubpixel/dpx_buttonode/issues/new?labels=enhancement&template=feature-request---.md">Request Feature</a>
    ·
    <a href="https://github.com/dubpixel/dpx_raxda_rockpis">🖨️ 3D Case for Rock Pi S</a>
    ·
    <a href="#dpx-buttonode-ui">📸 Screenshots</a>
    </p>
</div>

<div align="center">
  <img src="images/front.png" alt="dpx-buttonode hardware" width="600">
</div>

   <br />
<!-- TABLE OF CONTENTS -->
<details>
  <summary><h3>Table of Contents</h3></summary>
<ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li><a href="#usage">Usage</a></li>
    <li><a href="#dpx-buttonode-ui">dpx-buttonode-ui — Device Config UI</a></li>
    <li><a href="#reflection">Reflection</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact">Contact</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
</ol>
</details>
<!-- ABOUT THE PROJECT -->
<details>
<summary><h3>About The Project</h3></summary>

This project extends the architecture of <a href="https://github.com/elliotmatson/companion-satellite-armbian">companion-satellite-armbian</a>
to run on ARM single-board computers that aren't Raspberry Pis — turning any supported board into a
<strong>Bitfocus Companion Satellite</strong> node (or a full <strong>Bitfocus Companion</strong> instance, on the Full image
variant) out of the box. <strong>Bitfocus Buttons USB Relay</strong> is also supported as a third mode, for boards
dedicated to driving a physical USB relay instead.

The build pipeline is fully automated via GitHub Actions:
<ol>
  <li>The Armbian build framework compiles a minimal Ubuntu Noble (24.04) base image for the target board.</li>
  <li>HashiCorp Packer chroots into the image, installs Companion Satellite from source via the official install script,
  installs Bitfocus Buttons USB Relay from this repo's <code>buttons-deb-mirror</code> release (maintained manually — no
  Bitfocus account or secrets needed in CI), and — on the Full variant — installs full Bitfocus Companion itself.
  All modes are installed; <strong>Companion Satellite is the default active mode</strong>, switchable to Buttons or
  Companion at runtime with no re-flash.</li>
  <li>On first boot, <code>dpx-set-hostname.service</code> reads the board's Ethernet MAC address from sysfs and permanently sets the hostname to <code>dpx-buttonode-XXXX</code> (last 4 hex chars, e.g. <code>dpx-buttonode-C833</code>).</li>
  <li>The image is zeroed, gzip-compressed, and published as a GitHub Release.</li>
</ol>

> **Note on build time:** Companion Satellite is built from source inside the chroot (Node.js + Yarn build). This adds ~30–60 minutes to the total build time; the Full variant adds more on top for the full Companion install.

A daily scheduled workflow checks whether the mirror release has a version that hasn't been built yet, and automatically triggers a full matrix build if so.

</br>

*author(s): // www.dubpixel.tv  - i@dubpixel.tv*
</br>
</details>
<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Built With

* [Armbian Build Framework](https://github.com/armbian/build) — base Linux image for ARM SBCs
* [HashiCorp Packer](https://www.packer.io/) + [arm-image plugin](https://github.com/solo-io/packer-plugin-arm-image) — chroot image customization
* [GitHub Actions](https://github.com/features/actions) — CI/CD build, scheduling, and release publishing
* [Bitfocus Buttons USB Relay (headless)](https://bitfocus.io/buttons) — USB relay mode
* [Bitfocus Companion Satellite](https://github.com/bitfocus/companion-satellite) — Companion satellite mode
<p align="right">(<a href="#readme-top">back to top</a>)</p>
<!-- GETTING STARTED -->

## Getting Started

> **Pick your path:**
> - [**→ I just want to flash a board**](#-path-a--flash-a-pre-built-image) — download, flash, done
> - [**→ Bitfocus released a new version**](#-path-b--update-to-a-new-buttons-version) — one command to update the pipeline
> - [**→ I need a board not in the auto-release list**](#-path-c--build-any-other-board-manually) — manual dispatch for any of 150+ boards

---

### Supported Boards

The following boards are built **automatically** on every new Buttons release and published to [Releases](https://github.com/dubpixel/dpx_buttonode/releases):

| Board | Armbian ID |
|---|---|
| [Rock Pi S](https://wiki.radxa.com/RockpiS) — [buy](https://shop.allnetchina.cn/products/rock-pi-s) | `rockpi-s` |
| [Orange Pi Zero 3](http://www.orangepi.org/html/hardWare/computerAndMicrocontrollers/details/Orange-Pi-Zero-3.html) — [buy](https://www.aliexpress.com/item/1005005466373794.html) | `orangepizero3` |
| [Rock Pi 4B](https://wiki.radxa.com/Rockpi4) | `rockpi-4b` |
| [Rock Pi 4B+](https://wiki.radxa.com/Rockpi4) | `rockpi-4bplus` |
| [Rock Pi S0](https://radxa.com/products/rockpi/s0) | `rock-s0` |

#### Recommended accessories

| Accessory | Board | Why |
|---|---|---|
| [Rock Pi S PoE HAT](https://shop.allnetchina.cn/products/rock-pi-s-poe-hat) | Rock Pi S | Dedicated HAT — cleanest single-cable install |
| [ecoPI S housing](https://shop.allnetchina.cn/products/rock-pi-s-case) | Rock Pi S | Enclosure designed for Rock Pi S |
| [Waveshare PoE Splitter USB-C 2.5A](https://www.waveshare.com/poe-splitter-type-c.htm) | Orange Pi Zero 3 | PoE → USB-C 5V/2.5A, metal case, gigabit |
| [Waveshare PoE Splitter USB-C 5A](https://www.waveshare.com/poe-splitter-25w-type-c.htm) | Orange Pi Zero 3 | Same but 25W — more headroom for heavier loads |

All 150+ [Armbian-supported boards](https://www.armbian.com/download/) are available for one-off manual builds — see [Path C](#-path-c--build-any-other-board-manually).

---

### ✅ Path A — Flash a pre-built image

**What you need:** A microSD card (8 GB min), your Rock Pi board, a Stream Deck.

#### 1. Download the image

Go to [**Releases**](https://github.com/dubpixel/dpx_buttonode/releases) and download the `.img.gz` for your board.
Each release ships two variants — pick one:

- **`lite`** — Buttons USB Relay + Companion Satellite (smaller image, the default)
- **`full`** — everything in `lite`, plus full [Bitfocus Companion](https://bitfocus.io/companion) itself installed

```
rockpi-s-dpx-buttonode-<version>-lite.img.gz
rockpi-s-dpx-buttonode-<version>-full.img.gz
```

#### 2. Flash to SD card

**Easiest — [Balena Etcher](https://etcher.balena.io/) (Mac / Windows / Linux):**
1. Open Etcher → **Flash from file** → pick the `.img.gz`
2. Select your SD card
3. Click **Flash** — Etcher handles the `.gz` decompression automatically

**Command line (macOS):**
```bash
# Find your SD card — look for the right size disk
diskutil list

diskutil unmountDisk /dev/diskN
gunzip -c rockpi-s-dpx-buttonode-0.1.0-beta.4.img.gz \
  | sudo dd of=/dev/rdiskN bs=4m status=progress
diskutil eject /dev/diskN
```

**Command line (Linux):**
```bash
lsblk   # find your SD card device

gunzip -c rockpi-s-dpx-buttonode-0.1.0-beta.4.img.gz \
  | sudo dd of=/dev/sdX bs=4M status=progress conv=fsync
```

> ⚠️ Triple-check your device path (`/dev/diskN` or `/dev/sdX`). Wrong device = wiped disk.

#### 3. Boot and connect

1. Insert SD card into the Rock Pi
2. Plug in your Stream Deck via USB
3. Plug in ethernet
4. Power on — wait ~30 seconds

**That's it.** Open **Bitfocus Buttons** on your computer — the relay appears automatically under discovered devices. No configuration needed.

> **Hostname:** Each device gets a unique hostname derived from its MAC address: `dpx-buttonode-XXXX.local` where `XXXX` is the last 4 hex characters of the MAC (e.g. `dpx-buttonode-C833.local`). This is stable — the same board always gets the same name.

> **Web UI:** A device config panel runs on port 8080: `http://dpx-buttonode-XXXX.local:8080` — change hostname, switch DHCP/static IP, manage devices, discover other buttonodes, and **switch between Buttons and Satellite mode**.

> **SSH:** enabled — `ssh root@dpx-buttonode-XXXX.local` — default password `1234` (Armbian forces a change on first login).

---

### 🔄 Path B — Update to a new Buttons version

When Bitfocus releases a new version, this is the **entire process**:

#### 1. Download the new package from Bitfocus

Go to [user.bitfocus.io/download](https://user.bitfocus.io/download), log in, and download:
```
bitfocus-buttons-usb-relay-headless_X.Y.Z_arm64.tar.gz
```

#### 2. Upload it to the mirror (one command)

> Requires [GitHub CLI](https://cli.github.com/): `brew install gh` then `gh auth login`

```bash
./scripts/upload-mirror.sh ~/Downloads/bitfocus-buttons-usb-relay-headless_X.Y.Z_arm64.tar.gz
```

This uploads the file to the `buttons-deb-mirror` release in this repo. Done.

#### 3. Let CI do the rest (or trigger immediately)

The daily scheduled check at 06:00 UTC will detect the new version and automatically build all boards and publish a release.

To trigger it **right now** instead of waiting:
```bash
gh workflow run release-action.yaml --repo dubpixel/dpx_buttonode
```

Watch it: **Actions → Release — dpx-buttonode Images → latest run**

---

### 🛠 Path C — Build any other board manually

Any of the 150+ Armbian-supported boards can be built on demand. The artifact is available for 7 days under the Actions run (not published as a public release).

**Via GitHub web UI:**
1. Go to **Actions → Build Armbian + dpx-buttonode Image**
2. Click **Run workflow**
3. Pick your board from the dropdown
4. Click **Run workflow**
5. Wait ~45-90 min, then download the `.img.gz` from the run's Artifacts section

**Via terminal:**
```bash
gh workflow run armbian-builder.yaml \
  --repo dubpixel/dpx_buttonode \
  -f armbian-board=orangepizero3
```

Replace `orangepizero3` with any board ID from the [Armbian hardware list](https://www.armbian.com/download/).

---

### ⚙️ Fork and run your own pipeline

1. Fork this repo on GitHub
2. Seed the mirror with the current package:
   ```bash
   ./scripts/upload-mirror.sh ~/Downloads/bitfocus-buttons-usb-relay-headless_0.1.0-beta.4_arm64.tar.gz
   ```
3. Trigger a first build:
   - **Actions → Release — dpx-buttonode Images → Run workflow → Force: true**
4. Done — updates are fully automated from here

> No GitHub Secrets needed. The pipeline uses only the built-in `GITHUB_TOKEN`.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- USAGE EXAMPLES -->
## Usage

<a id="dpx-buttonode-ui"></a>

## dpx-buttonode-ui — Device Config Web Interface

Every device runs a lightweight web UI on **port 8080**:

```
http://dpx-buttonode-XXXX.local:8080
```

<div align="center">
  <img src="images/001_status.jpe" alt="Status tab" width="480">
  <img src="images/002_hostname.jpe" alt="Hostname tab" width="480">
  <br/>
  <img src="images/003_network.jpe" alt="Network tab" width="480">
  <img src="images/004_devices.jpe" alt="Devices tab" width="480">
  <br/>
  <img src="images/005_nodes.jpe" alt="Nodes tab" width="480">
  <img src="images/006_mode.jpe" alt="Mode tab" width="480">
</div>

| Tab | What it does |
|---|---|
| **Status** | Hostname, IP, MAC, network mode, **current mode + active service status**, mDNS health, USB devices |
| **Hostname** | Change the device hostname — applies immediately and persists across reboots |
| **Network** | Switch between DHCP and static IP. Survives reboots. |
| **Devices** | USB device list, Stream Deck USB power cycle, Buttons service restart |
| **Nodes** | Discover all other `dpx-buttonode-*` units on the LAN with links to each web UI |
| **Mode** | Switch between Buttons and Satellite. Configure Companion server IP + port for Satellite mode. |

> **Note:** The Network tab writes directly to `/etc/systemd/network/` and restarts `systemd-networkd`. After an IP change, navigate to the new address — the hostname (`dpx-buttonode-XXXX.local`) resolves correctly via mDNS within a few seconds.

---

### SSH into the device

SSH ships **disabled**, and there's no hardcoded default credential — enable it from the web UI's **SSH**
tab. On first boot, a random per-device root password is generated automatically. It's deliberately
**never shown on the web UI itself** (that page has no login of its own) — the only place it's ever
revealed is the Stream Deck: **hold down the SSH key** (in the action row, next to GO) to display it for as
long as you're holding it. Seeing it requires physically being at the device.

1. On the Stream Deck, hold the **SSH** key to read the generated password.
2. Enter it in the web UI's **Enable SSH** form (or use it to `ssh` in directly — SSH being off just means
   the `ssh` service isn't running yet; enabling it from the UI starts it).
3. **Set your own password** via the same tab — this deletes the generated one, and the SSH key goes blank.

**No Stream Deck attached at first boot?** The generated password is not recoverable remotely by design —
there is currently no other way to retrieve it. Connect a deck temporarily (it only needs to be attached
long enough to hold the SSH key once) to get in, or reset the root password locally instead
(`sudo passwd root` via a serial console / direct login, if your board supports one).

```bash
ssh root@dpx-buttonode-XXXX.local
# where XXXX is the last 4 hex chars of the board's MAC address
```

If mDNS isn't resolving, find the IP from your router and use that directly.

> ⚠️ **Why this exists.** Every action on the SSH tab requires the *current* root password — that page has
> no login of its own (plain HTTP, reachable by anyone on the LAN), so without this check, "enable SSH from
> the web UI" would let anyone on the network turn SSH on with a password of their own choosing, no
> guessing required. Requiring the current password keeps the bar at "you already have root," the same as
> SSH access always implied, just reachable through the browser too. This is aimed at keeping honest people
> honest on a home/studio LAN — it is **not** hardened against a determined attacker with sustained LAN
> access. See `AGENTS.md` gotcha 10a for implementation details.

---

### Check which mode is active

```bash
cat /etc/dpx-mode   # prints: buttons  or  satellite
```

---

### Switch modes from the terminal

You can also switch from SSH — same as what the UI does:

```bash
# Switch to Satellite mode
systemctl stop bitfocus-buttons-usb-relay
systemctl disable bitfocus-buttons-usb-relay
systemctl enable satellite
systemctl start satellite
echo satellite > /etc/dpx-mode

# Switch back to Buttons mode
systemctl stop satellite
systemctl disable satellite
systemctl enable bitfocus-buttons-usb-relay
systemctl start bitfocus-buttons-usb-relay
echo buttons > /etc/dpx-mode
```

---

### Companion Satellite mode

In Satellite mode the device connects outbound to a running Bitfocus Companion instance and exposes the attached Stream Deck(s) as remote surfaces.

**Requirements:**
- Bitfocus Companion **v3.4.0 or newer** running somewhere on the network
- Companion must have **Satellite** enabled: _Settings → Surfaces → Enable Satellite_
- TCP port **16622** reachable from the dpx-buttonode to the Companion machine

**Configure from the web UI:**
1. Open `http://dpx-buttonode-XXXX.local:8080`
2. Go to the **Mode** tab
3. Enter your Companion server IP and port (default `16622`)
4. Click **Switch to Satellite** — the device switches immediately and persists on reboot

**Configure from SSH:**
```bash
# Write persistent config
cat > /etc/dpx-satellite.conf <<EOF
HOST=192.168.1.10
PORT=16622
EOF

# Stage it for satellite's boot import
cat > /boot/satellite-config <<EOF
COMPANION_IP=192.168.1.10
COMPANION_PORT=16622
EOF

# Or push it live to the running service via REST API
curl -X POST http://localhost:9999/api/config \
  -H 'Content-Type: application/json' \
  -d '{"host":"192.168.1.10","port":16622}'
```

**Check satellite status:**
```bash
systemctl status satellite
journalctl -u satellite -f

# REST API shows current config + connection status
curl http://localhost:9999/api/config
```

---

### Check the Buttons relay is running

```bash
# Is it running?
systemctl status bitfocus-buttons-usb-relay

# Watch live logs
journalctl -u bitfocus-buttons-usb-relay -f

# Restart it
sudo systemctl restart bitfocus-buttons-usb-relay
```

---

### Connect to a specific Buttons server (client mode)

By default the relay announces itself via mDNS and Buttons discovers it automatically — **no config needed** for most setups.

If your network blocks mDNS (some managed switches do), point the relay directly at your Buttons server:

```bash
sudo nano /etc/default/bitfocus-buttons-usb-relay
```

Add this line:
```
EXTRA_ARGS="-buttonsAddress 192.168.1.10:3000"
```

Then restart:
```bash
sudo systemctl restart bitfocus-buttons-usb-relay
```

---

### Network discovery

The device announces itself as `dpx-buttonode-XXXX.local` on port `3040` (Buttons relay) and port `8080` (web UI).

```bash
# Confirm it's on the network
ping dpx-buttonode-XXXX.local

# Discover all buttonodes on the LAN
avahi-browse -t _dpx-buttonode._tcp     # Linux
dns-sd -B _dpx-buttonode._tcp local     # macOS

# Or just open the Nodes tab in the web UI
```
<!-- REFLECTION -->
## Reflection

* what did we learn?
  - _x_
* what do we like/hate?
  - _y_
* what would/could we do differently?
  - _z_

<!-- ROADMAP -->

- [x] Core Armbian + Packer two-stage build pipeline
- [x] Self-hosted package mirror via GitHub Releases (no Bitfocus secrets in CI)
- [x] Matrix builds for Orange Pi Zero family
- [x] Daily automated version check + GitHub Release publishing
- [x] `upload-mirror.sh` helper for one-command package updates
- [x] Dynamic MAC-derived hostname (`dpx-buttonode-XXXX`) on first boot
- [x] `dpx-buttonode-ui` — device config web UI on port 8080 (hostname, network, devices, node discovery)
- [x] Companion Satellite A/B mode — both services baked in, switch without re-flash
- [x] Mode tab in web UI — configure Companion server IP/port, switch modes from browser
- [ ] Additional board support (Banana Pi M2 Zero, NanoPi R4S, Orange Pi 5)
- [ ] SHA256 checksums attached to each release
- [ ] WiFi pre-configuration support in image (via Armbian `wpa_supplicant` overlay)
- [ ] OTA image update — download latest release from GitHub and flash in-place (kexec into RAM, `dd` to SD, reboot)

See the [open issues](https://github.com/dubpixel/dpx_buttonode/issues) for a full list of proposed features (and known issues).

<!-- CONTRIBUTING -->
## Contributing

_Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**._

If you have a suggestion that would make this better, please fork the repo and create a pull request. You can also simply open an issue with the tag "enhancement".
Don't forget to give the project a star! Thanks again!

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

### Top contributors:
<a href="https://github.com/dubpixel/dpx_buttonode/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=dubpixel/dpx_buttonode" alt="contrib.rocks image" />
</a>

<!-- LICENSE -->
## License
Distributed under the [LICENSE_TYPE] License. See `LICENSE.txt` for more information.
<!-- CONTACT -->
## Contact

  ### Joshua Fleitell - i@dubpixel.tv

  Project Link: [https://github.com/dubpixel/dpx_buttonode](https://github.com/dubpixel/dpx_buttonode)

<!-- ACKNOWLEDGMENTS -->
## Acknowledgments

* [elliotmatson/companion-satellite-armbian](https://github.com/elliotmatson/companion-satellite-armbian) — architecture and workflow pattern this project is based on
* [Bitfocus](https://bitfocus.io/) — creators of Buttons and Companion
* [Armbian](https://www.armbian.com/) — Linux for ARM SBCs
* [Bitfocus Buttons USB Relay — Official Docs](https://support.bitfocus.io/hc/en-us/articles/33855997471890-Bitfocus-Buttons-USB-Relay-Raspberry-Pi) — source of truth for installation, service management, and configuration
* [Bitfocus Companion Satellite — GitHub](https://github.com/bitfocus/companion-satellite) — official install script and documentation
* [dpx_raxda_rockpis](https://github.com/dubpixel/dpx_raxda_rockpis) — 3D printable POE enclosure for the Rock Pi S hardware this project runs on

---

<details>
<summary><h3>🔧 How to replicate this pattern for any software</h3></summary>

This project uses a two-stage pipeline to produce flash-ready images for ARM SBCs. Here's the general recipe so you can adapt it for any headless software you want to bake into an Armbian image.

---

#### The pattern

```
GitHub Actions runner (x86)
  └─ 1. Build Armbian base image for target board
  └─ 2. Packer chroots into image via QEMU
       └─ copies your software in
       └─ installs it
       └─ configures it (hostname, services, etc.)
  └─ 3. Compress and publish the image
```

No cross-compilation. No physical board needed. Runs entirely on standard x86 CI runners.

---

#### What you need

- Your software packaged as a `.deb`, or an install script that runs inside a Debian/Ubuntu chroot
- A GitHub repo with Actions enabled
- [HashiCorp Packer](https://www.packer.io/) — free, open source

---

#### Step 1 — Write your Packer HCL file

Create `your-software.pkr.hcl`:

```hcl
packer {
  required_plugins {
    arm-image = {
      version = "0.2.7"
      source  = "github.com/solo-io/arm-image"
    }
  }
}

variable "url"      { type = string }  # path to Armbian .img
variable "deb_path" { type = string }  # path to your .deb

source "arm-image" "armbian" {
  iso_checksum    = "none"
  iso_url         = var.url
  target_image_size = 5000000000        # 5 GB — adjust as needed
  output_filename = "output/image.img"
  qemu_binary     = "qemu-aarch64-static"
  image_mounts    = ["/"]

  # Required for DNS to work inside the chroot
  additional_chroot_mounts = [["bind", "/run/systemd", "/run/systemd"]]
}

build {
  sources = ["source.arm-image.armbian"]

  # Copy your software into the image
  provisioner "file" {
    source      = var.deb_path
    destination = "/tmp/your-software.deb"
  }

  # Copy your install script
  provisioner "file" {
    source      = "scripts/install.sh"
    destination = "/tmp/install.sh"
  }

  # System config (hostname, first-login, SSH)
  provisioner "shell" {
    inline = [
      "rm -f /root/.not_logged_in_yet",
      "echo your-device-name > /etc/hostname",
      "systemctl disable ssh || true",
    ]
  }

  # Install your software (runs as root)
  provisioner "shell" {
    execute_command = "chmod +x {{ .Path }}; {{ .Vars }} su root -c {{ .Path }}"
    inline_shebang  = "/bin/bash -e"
    inline          = ["chmod +x /tmp/install.sh", "/tmp/install.sh"]
  }
}
```

---

#### Step 2 — Write your install script

`scripts/install.sh` runs **inside the chroot** as root. Treat it like a normal Debian post-install script:

```bash
#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# Install dependencies
apt-get update -q
apt-get install -y --no-install-recommends avahi-daemon libusb-1.0-0

# Install your package
dpkg -i /tmp/your-software.deb || apt-get install -f -y

# Enable services
systemctl enable your-service
systemctl enable avahi-daemon

# Cleanup
apt-get clean
```

---

#### Step 3 — Wire it into GitHub Actions

```yaml
- name: Install QEMU (required for ARM chroot on x86 runners)
  run: sudo apt-get install -y qemu-user-static

- name: Build Armbian base image
  run: |
    git clone --depth=1 https://github.com/armbian/build build
    sudo ./build/compile.sh build \
      BOARD=your-board-id \
      BRANCH=current \
      RELEASE=noble \
      BUILD_MINIMAL=yes \
      KERNEL_CONFIGURE=no \
      COMPRESS_OUTPUTIMAGE=no
    sudo mv build/output/images/*.img build/output/images/armbian.img

- name: Install Packer
  run: |
    wget -qO - https://apt.releases.hashicorp.com/gpg \
      | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
    echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] \
      https://apt.releases.hashicorp.com $(lsb_release -cs) main" \
      | sudo tee /etc/apt/sources.list.d/hashicorp.list
    sudo apt-get update -q && sudo apt-get install -y packer

- name: Run Packer
  run: |
    sudo packer init your-software.pkr.hcl
    sudo packer build \
      -var "url=build/output/images/armbian.img" \
      -var "deb_path=path/to/your-software.deb" \
      your-software.pkr.hcl

- name: Compress image
  run: |
    sudo apt-get install -y zerofree
    IMG="output/image.img"
    LOOP=$(sudo losetup -fP --show "$IMG")
    sudo e2fsck -fy "${LOOP}p1" || true
    sudo zerofree "${LOOP}p1"
    sudo losetup -d "$LOOP"
    gzip -n "$IMG"
```

---

#### Key things to know

| Thing | Why it matters |
|---|---|
| `qemu-user-static` must be installed **before** Packer runs | Packer uses it to emulate ARM64 instructions inside the chroot on your x86 runner |
| `additional_chroot_mounts = [["bind", "/run/systemd", "/run/systemd"]]` | Without this, DNS resolution inside the chroot fails and `apt-get` can't reach package servers |
| All `packer` commands need `sudo` | The `arm-image` plugin creates loop devices and bind mounts — root required |
| `sudo mv` the Armbian output | The Armbian build framework runs as root inside Docker, so output files are owned by root |
| `zerofree` before `gzip` | Zeros unused filesystem blocks so the image compresses 3-5x smaller |
| Set `target_image_size` generously | Packer will fail if the image fills up during install. 5 GB is safe for most software |

---

#### Supported boards

Any board in [Armbian's supported hardware list](https://www.armbian.com/download/) works. Look up the board's `BOARD=` ID from the Armbian docs or the [supported boards list](https://github.com/armbian/build/blob/main/config/boards).

</details>

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- MARKDOWN LINKS & IMAGES -->
<!-- https://www.markdownguide.org/basic-syntax/#reference-style-links -->
[contributors-shield]: https://img.shields.io/github/contributors/dubpixel/dpx_buttonode.svg?style=flat-square
[contributors-url]: https://github.com/dubpixel/dpx_buttonode/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/dubpixel/dpx_buttonode.svg?style=flat-square
[forks-url]: https://github.com/dubpixel/dpx_buttonode/network/members
[stars-shield]: https://img.shields.io/github/stars/dubpixel/dpx_buttonode.svg?style=flat-square
[stars-url]: https://github.com/dubpixel/dpx_buttonode/stargazers
[issues-shield]: https://img.shields.io/github/issues/dubpixel/dpx_buttonode.svg?style=flat-square
[issues-url]: https://github.com/dubpixel/dpx_buttonode/issues
[license-shield]: https://img.shields.io/github/license/dubpixel/dpx_buttonode.svg?style=flat-square
[license-url]: https://github.com/dubpixel/dpx_buttonode/blob/main/LICENSE.txt
[linkedin-shield]: https://img.shields.io/badge/-LinkedIn-black.svg?style=flat-square&logo=linkedin&colorB=555
[linkedin-url]: https://linkedin.com/in/jfleitell
[product-front]: images/front.png
[product-rear]: images/rear.png
[product-front-rendering]: images/front_render.png
[product-rear-rendering]: images/rear_render.png
[product-pcbFront]: images/pcb_front.png
[product-pcbRear]: images/pcb_rear.png
[Next.js]: https://img.shields.io/badge/next.js-000000?style=for-the-badge&logo=nextdotjs&logoColor=white
[Next-url]: https://nextjs.org/
[React.js]: https://img.shields.io/badge/React-20232A?style=for-the-badge&logo=react&logoColor=61DAFB
[React-url]: https://reactjs.org/
[Vue.js]: https://img.shields.io/badge/Vue.js-35495E?style=for-the-badge&logo=vuedotjs&logoColor=4FC08D
[Vue-url]: https://vuejs.org/
[Angular.io]: https://img.shields.io/badge/Angular-DD0031?style=for-the-badge&logo=angular&logoColor=white
[Angular-url]: https://angular.io/
[Svelte.dev]: https://img.shields.io/badge/Svelte-4A4A55?style=for-the-badge&logo=svelte&logoColor=FF3E00
[Svelte-url]: https://svelte.dev/
[Laravel.com]: https://img.shields.io/badge/Laravel-FF2D20?style=for-the-badge&logo=laravel&logoColor=white
[Laravel-url]: https://laravel.com
[Bootstrap.com]: https://img.shields.io/badge/Bootstrap-563D7C?style=for-the-badge&logo=bootstrap&logoColor=white
[Bootstrap-url]: https://getbootstrap.com
[JQuery.com]: https://img.shields.io/badge/jQuery-0769AD?style=for-the-badge&logo=jquery&logoColor=white
[JQuery-url]: https://jquery.com 
[KiCad.org]: https://img.shields.io/badge/KiCad-v8.0.6-blue
[KiCad-url]: https://kicad.org 
[Fusion-360]: https://img.shields.io/badge/Fusion360-v4.2.0-green
[Autodesk-url]: https://autodesk.com 
[FastLed.io]: https://img.shields.io/badge/FastLED-v3.9.9-red
[FastLed-url]: https://fastled.io 
