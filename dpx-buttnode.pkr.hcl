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
  description = "dpx-buttnode project version (from VERSION file)"
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
  output_filename   = "output-dpx-buttnode/armbian-dpx-buttnode.img"
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

  # Copy the device config web UI (installed to /usr/local/bin by install-buttons.sh)
  provisioner "file" {
    source      = "src/dpx-buttnode-ui/dpx-buttnode-ui.py"
    destination = "/tmp/dpx-buttnode-ui.py"
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
      # with dpx-buttnode-XXXX (MAC-derived) on first boot.
      "echo dpx-buttnode > /etc/hostname",
      "sed -i \"s/127.0.1.1.*/127.0.1.1\\tdpx-buttnode/\" /etc/hosts || true",

      # SSH enabled for remote access and debugging
      # Login: root / 1234  (Armbian forces a password change on first login)
      "systemctl enable ssh || true",

      # Write build metadata — readable by dpx-buttnode-ui Status page
      "echo 'DPX_VERSION=${var.dpx_version}' > /etc/dpx-buttnode-release",
      "echo 'BUTTONS_VERSION=${var.build}' >> /etc/dpx-buttnode-release",
      "echo 'GIT_BRANCH=${var.git_branch}' >> /etc/dpx-buttnode-release",
      "echo 'GIT_COMMIT=${var.git_commit}' >> /etc/dpx-buttnode-release",
      "echo 'BUILD_DATE=${var.build_date}' >> /etc/dpx-buttnode-release",
      # Lite variant flag — install-companion.sh overwrites VARIANT to 'full' if run
      "echo 'VARIANT=${var.variant}' >> /etc/dpx-buttnode-release",
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

  # Copy the Companion Satellite install script into the image
  provisioner "file" {
    source      = "scripts/install-satellite.sh"
    destination = "/tmp/install-satellite.sh"
  }

  # Install Companion Satellite (headless, stable build — runs as root)
  # Downloads from GitHub inside the chroot; requires internet access.
  # Installs but leaves disabled by default (dpx-buttnode-ui Mode tab activates it).
  provisioner "shell" {
    execute_command = "chmod +x {{ .Path }}; {{ .Vars }} su root -c {{ .Path }}"
    inline_shebang  = "/bin/bash -e"
    inline = [
      "chmod +x /tmp/install-satellite.sh",
      "/tmp/install-satellite.sh"
    ]
  }

  # ── Full variant only: install Bitfocus Companion ──────────────────────────
  # Skipped on lite builds. Companion is a pre-built arm64 download (~500MB-2GB).
  # Adds ~15-25 min to build time (download + extract, no compile step).
  provisioner "file" {
    source      = "scripts/install-companion.sh"
    destination = "/tmp/install-companion.sh"
  }

  provisioner "shell" {
    execute_command = "chmod +x {{ .Path }}; {{ .Vars }} su root -c {{ .Path }}"
    inline_shebang  = "/bin/bash -e"
    inline = [
      "chmod +x /tmp/install-companion.sh",
      "if [ '${var.variant}' = 'full' ]; then /tmp/install-companion.sh; else echo '==> Skipping Companion install (lite variant)'; fi"
    ]
  }
}
