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

variable "image_mounts" {
  type    = list(string)
  default = ["/"]
  description = <<-EOT
    Mount points, one per partition, in partition-index order (partition 1
    first). Armbian's single-partition images use the default ["/"].
    Raspberry Pi OS ships two partitions (boot, then root) and needs
    ["/boot", "/"] -- the arm-image Packer plugin hard-requires
    len(partitions) == len(image_mounts) (pkg/builder/step_mount_image.go),
    so this must match the actual source image's partition count exactly
    or the build fails with "different of partitions than expected".
    Confirmed live 2026-08-29 building against a real Raspberry Pi OS image.
  EOT
}

source "arm-image" "base" {
  iso_checksum      = "none"
  iso_url           = var.url
  target_image_size = var.variant == "full" ? 8000000000 : 5000000000
  output_filename   = "output-dpx-buttonode/dpx-buttonode.img"
  image_arch      = "arm64"
  qemu_binary     = "qemu-aarch64-static"
  image_mounts    = var.image_mounts

  # Needed for DNS to work inside the chroot on newer Armbian/Raspberry Pi OS images
  additional_chroot_mounts = [["bind", "/run/systemd", "/run/systemd"]]
}

build {
  # Source is named "base", not "armbian" -- this same block builds both
  # the Armbian pipeline (armbian-builder.yaml) and the Raspberry Pi OS
  # pipeline (raspios-builder.yaml); naming it "armbian" made every build
  # log line read "arm-image.armbian: ..." even for real Pi OS builds.
  sources = ["source.arm-image.base"]

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
      # Stub out update-initramfs for the whole chroot session, BEFORE any
      # apt-get install runs anywhere in this build. Root cause of a real,
      # already-confirmed boot failure in the sibling dpx_openPanel project
      # (same Packer arm-image + qemu chroot toolchain): some package's
      # postinst hook triggers dpkg's initramfs-tools trigger, which runs
      # `update-initramfs` and Raspberry Pi OS's own hook then copies the
      # result straight into the FAT32 boot partition. That's a ~50MB write
      # into a small FAT32 filesystem via QEMU-emulated I/O inside the
      # chroot, and it can corrupt the filesystem badly enough that the
      # Pi's bootloader can't read the boot partition on real hardware --
      # even though the resulting image still passes fsck.fat and a manual
      # MBR check, and the build itself reports success. This device
      # doesn't use or need an initramfs for normal SD boot, so stubbing
      # the hook out is safe -- same technique pi-gen (the tool Raspberry
      # Pi OS itself is built with) uses, for the same reason. Suspected
      # root cause of inconsistent real-hardware boot stalls seen
      # 2026-08-29/30 on real Pi 4 (different symptom each time -- cloud-init
      # target, graphical.target, multi-user.target with SSH also
      # unreachable -- consistent with filesystem corruption rather than
      # one specific service bug, since the targeted fixes for each
      # individual symptom didn't actually resolve the underlying stall).
      "cat > /usr/sbin/update-initramfs << 'STUB'",
      "#!/bin/sh",
      "exit 0",
      "STUB",
      "chmod +x /usr/sbin/update-initramfs",

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
      #
      # Must disable ssh.socket too, not just ssh.service — confirmed
      # live 2026-08-28 that a fresh image with only ssh.service disabled
      # was still fully SSH-reachable the entire time. Ubuntu ships
      # ssh.socket enabled alongside ssh.service; socket activation means
      # systemd listens on :22 and lazily starts ssh.service on the first
      # connection attempt regardless of the service's own state.
      #
      # No --now here (see gotcha #18) — it's meaningless at image-build
      # time (nothing is running in the chroot) and Raspberry Pi OS
      # Trixie's newer systemd hard-refuses it, unlike Armbian's older
      # systemd which silently no-ops it. Plain disable removes the
      # enable symlink, which is all that's needed.
      "systemctl disable ssh.socket || true",
      "systemctl disable ssh.service || true",

      # Raspberry Pi OS ships a placeholder UID-1000 user and a
      # userconfig.service that interactively prompts "Which user would
      # you like to rename:" on /dev/tty8 on every boot unless
      # /boot/firmware/userconf.txt is pre-seeded -- confirmed live
      # 2026-08-29 on real Pi 4 hardware (see dpx_openPanel issue #25 for
      # the same class of problem in a sibling project). This project's
      # security model is root-only SSH with no baked-in credential (see
      # the SSH block above) -- we don't want or need this separate
      # non-root account/wizard at all, so mask it outright rather than
      # fake a userconf.txt. No-op (but harmless) on Armbian, which
      # doesn't ship this unit.
      "systemctl mask userconfig.service || true",

      # Raspberry Pi OS ships cloud-init by default (it's the actual
      # mechanism behind Raspberry Pi Imager's "advanced options"
      # customization on current releases). With no datasource/config
      # provided, it searches before giving up on its own timeout --
      # confirmed live 2026-08-29, boot visibly stalled at "Reached
      # target Cloud-init target" on real Pi 4 hardware. This project's
      # own first-boot provisioning (dpx-set-hostname, dpx-init-ssh, etc.)
      # already covers everything cloud-init would otherwise be used for
      # here, so disable it outright via its own documented marker file
      # rather than let it search-and-timeout on every boot. Also mask
      # the units directly as a second layer -- harmless if redundant.
      # No-op (but harmless) on Armbian, which may not ship cloud-init
      # depending on board/image.
      "mkdir -p /etc/cloud && touch /etc/cloud/cloud-init.disabled || true",
      "systemctl mask cloud-init.service cloud-init-local.service cloud-config.service cloud-final.service cloud-init.target || true",

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

  # ── Companion Dashboard (opt-in kiosk display) ──────────────────────────────
  # Runs on BOTH variants — Dashboard is orthogonal to the Buttons/Satellite/
  # Companion mode system, not gated by `variant`. Installed but not enabled;
  # the web UI's Devices tab toggle is what starts it (see install-dashboard.sh).
  provisioner "file" {
    source      = "scripts/install-dashboard.sh"
    destination = "/tmp/install-dashboard.sh"
  }

  provisioner "shell" {
    execute_command = "chmod +x {{ .Path }}; {{ .Vars }} su root -c {{ .Path }}"
    inline_shebang  = "/bin/bash -e"
    inline = [
      "chmod +x /tmp/install-dashboard.sh",
      "/tmp/install-dashboard.sh"
    ]
  }
}
