packer {
  required_plugins {
    arm-image = {
      version = "0.2.7"
      source  = "github.com/solo-io/arm-image"
    }
  }
}

variable "url" {
  type    = string
  default = ""
}

variable "build" {
  type    = string
  default = "latest"
}

variable "deb_path" {
  type    = string
  default = "artifacts/bitfocus-buttons-usb-relay-headless.deb"
  description = "Local path to the downloaded .deb package, relative to the build root"
}

variable "dpx_version" {
  type    = string
  default = "dev"
  description = "dpx-buttonode project version (from VERSION file)"
}

variable "git_branch" {
  type    = string
  default = "local"
  description = "Git branch this image was built from"
}

variable "git_commit" {
  type    = string
  default = "unknown"
  description = "Short git commit SHA"
}

variable "build_date" {
  type    = string
  default = "unknown"
  description = "ISO date this image was built (UTC)"
}

variable "variant" {
  type    = string
  default = "lite"
  description = "Image variant: 'lite' (Buttons + Satellite) or 'full' (+ full Companion)"
}

source "arm-image" "armbian" {
  iso_checksum      = "none"
  iso_url           = var.url
  target_image_size = var.variant == "full" ? 8000000000 : 5000000000
  output_filename   = "output-dpx-buttonode/armbian-dpx-buttonode.img"
  qemu_binary     = "qemu-aarch64-static"
  image_mounts    = ["/"]

  # Needed for DNS to work inside the chroot on newer Armbian images
  additional_chroot_mounts = [["bind", "/run/systemd", "/run/systemd"]]
}

build {
  sources = ["source.arm-image.armbian"]

  # Copy the pre-downloaded .deb into the image
  provisioner "file" {
    source      = var.deb_path
    destination = "/tmp/bitfocus-buttons-usb-relay-headless.deb"
  }

  # Copy the install script into the image
  provisioner "file" {
    source      = "scripts/install-buttons.sh"
    destination = "/tmp/install-buttons.sh"
  }

  # Copy the dynamic-hostname script (installed to /usr/local/bin by install-buttons.sh)
  provisioner "file" {
    source      = "scripts/dpx-set-hostname.sh"
    destination = "/tmp/dpx-set-hostname.sh"
  }

  # Copy the first-boot SSH password generator (installed by install-buttons.sh)
  provisioner "file" {
    source      = "scripts/dpx-init-ssh.sh"
    destination = "/tmp/dpx-init-ssh.sh"
  }

  # Copy the device config web UI (installed to /usr/local/bin by install-buttons.sh)
  provisioner "file" {
    source      = "src/dpx-buttonode-ui/dpx-buttonode-ui.py"
    destination = "/tmp/dpx-buttonode-ui.py"
  }

  provisioner "file" {
    source      = "images/fav_icon.png"
    destination = "/tmp/fav_icon.png"
  }

  # System configuration (hostname, first-login cleanup, SSH)
  provisioner "shell" {
    inline = [
      # Disable Armbian first-login prompt
      "rm -f /root/.not_logged_in_yet",

      # Set a placeholder hostname — dpx-set-hostname.service replaces this
      # with dpx-buttonode-XXXX (MAC-derived) on first boot.
      "echo dpx-buttonode > /etc/hostname",
      "sed -i \"s/127.0.1.1.*/127.0.1.1\\tdpx-buttonode/\" /etc/hosts || true",

      # SSH DISABLED by default — no default credential to ship at all.
      # dpx-init-ssh.service generates a random per-device root password
      # on first boot (shown on the deck splash + the web UI's SSH tab
      # until changed); the web UI's SSH tab is the only way to enable
      # SSH itself. See README's security section / AGENTS.md gotcha 10a.
      "systemctl disable ssh || true",

      # Write build metadata — readable by dpx-buttonode-ui Status page
      "echo 'DPX_VERSION=${var.dpx_version}' > /etc/dpx-buttonode-release",
      "echo 'BUTTONS_VERSION=${var.build}' >> /etc/dpx-buttonode-release",
      "echo 'GIT_BRANCH=${var.git_branch}' >> /etc/dpx-buttonode-release",
      "echo 'GIT_COMMIT=${var.git_commit}' >> /etc/dpx-buttonode-release",
      "echo 'BUILD_DATE=${var.build_date}' >> /etc/dpx-buttonode-release",
      # Lite variant flag — install-companion.sh overwrites VARIANT to 'full' if run
      "echo 'VARIANT=${var.variant}' >> /etc/dpx-buttonode-release",
    ]
  }

  # Install Bitfocus Buttons USB Relay (runs as root)
  provisioner "shell" {
    execute_command = "chmod +x {{ .Path }}; {{ .Vars }} su root -c {{ .Path }}"
    inline_shebang  = "/bin/bash -e"
    inline = [
      "export BUTTONS_BUILD=${var.build}",
      "chmod +x /tmp/install-buttons.sh",
      "/tmp/install-buttons.sh"
    ]
  }

  # Copy the deck-splash script + installer into the image.
  # Runs after install-buttons.sh — needs the `buttons` group + hidraw
  # udev rule that package creates.
  provisioner "file" {
    source      = "src/dpx-deck-splash/dpx-deck-splash.py"
    destination = "/tmp/dpx-deck-splash.py"
  }

  provisioner "file" {
    source      = "scripts/install-deck-splash.sh"
    destination = "/tmp/install-deck-splash.sh"
  }

  provisioner "shell" {
    execute_command = "chmod +x {{ .Path }}; {{ .Vars }} su root -c {{ .Path }}"
    inline_shebang  = "/bin/bash -e"
    inline = [
      "chmod +x /tmp/install-deck-splash.sh",
      "/tmp/install-deck-splash.sh"
    ]
  }

  # ── Full variant only: install Bitfocus Companion ──────────────────────────
  # Skipped on lite builds. Companion is a pre-built arm64 download (~500MB-2GB).
  # Adds ~15-25 min to build time (download + extract, no compile step).
  #
  # MUST run before install-satellite.sh, not after — discovered the hard way
  # 2026-08-26. companion-pi's own official installer unconditionally purges
  # /opt/fnm as its final step ("fnm is no longer used by the modern flow"),
  # but Satellite's systemd unit and our install-satellite.sh/update-satellite.sh
  # both hard-depend on /opt/fnm/aliases/default/bin/node. Satellite's own
  # installer freshly reprovisions /opt/fnm every time it runs, so as long as
  # it runs LAST, this is a non-issue — but with the old order (Satellite then
  # Companion), every full-variant build shipped with Satellite silently broken
  # from first boot (systemd: "Control process exited, code=exited, status=203/EXEC").
  provisioner "file" {
    source      = "scripts/install-companion.sh"
    destination = "/tmp/install-companion.sh"
  }

  # Copy the Companion on-device update script (installed to
  # /usr/local/bin by install-companion.sh, invoked by the Updates tab)
  provisioner "file" {
    source      = "scripts/update-companion.sh"
    destination = "/tmp/update-companion.sh"
  }

  provisioner "shell" {
    execute_command = "chmod +x {{ .Path }}; {{ .Vars }} su root -c {{ .Path }}"
    inline_shebang  = "/bin/bash -e"
    inline = [
      "chmod +x /tmp/install-companion.sh",
      "if [ '${var.variant}' = 'full' ]; then /tmp/install-companion.sh; else echo '==> Skipping Companion install (lite variant)'; fi"
    ]
  }

  # Copy the Companion Satellite install script into the image
  provisioner "file" {
    source      = "scripts/install-satellite.sh"
    destination = "/tmp/install-satellite.sh"
  }

  # Copy the Companion Satellite on-device update script (installed to
  # /usr/local/bin by install-satellite.sh, invoked by the Updates tab)
  provisioner "file" {
    source      = "scripts/update-satellite.sh"
    destination = "/tmp/update-satellite.sh"
  }

  # Install Companion Satellite (headless, stable build — runs as root)
  # Downloads from GitHub inside the chroot; requires internet access.
  # Installs but leaves disabled by default (dpx-buttonode-ui Mode tab activates it).
  # Runs LAST (after Companion, on full-variant builds) — see the fnm-purge
  # note on the Companion block above for why the order matters.
  provisioner "shell" {
    execute_command = "chmod +x {{ .Path }}; {{ .Vars }} su root -c {{ .Path }}"
    inline_shebang  = "/bin/bash -e"
    inline = [
      "chmod +x /tmp/install-satellite.sh",
      "/tmp/install-satellite.sh"
    ]
  }
}
