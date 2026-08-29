# Regression-tests the Bitfocus Buttons USB Relay .deb install/update
# lifecycle — NOT real button/HID behavior, which needs actual hardware
# and can't be provided by a container. Confirms: does the mirrored .deb
# still install cleanly, does its service process start, does installing
# a newer .deb over it (the same operation apply_buttons_update() does on
# a real device) still work.
#
# The buttons-deb-mirror release only publishes arm64 builds (the real
# target is an ARM SBC) — there is no amd64 build to fall back to. This
# image is pinned to linux/arm64 and MUST be run under QEMU emulation on
# an amd64 droplet. One-time host setup (not part of this Dockerfile):
#   docker run --privileged --rm tonistiigi/binfmt --install arm64
# See ../README.md.
FROM --platform=linux/arm64 debian:bookworm-slim

RUN printf '#!/bin/sh\necho "[systemctl stub] ignoring: $*"\nexit 0\n' \
        > /usr/local/bin/systemctl \
    && chmod +x /usr/local/bin/systemctl

RUN apt-get update -q && apt-get install -yq --no-install-recommends \
        curl ca-certificates libusb-1.0-0 libudev1 avahi-daemon avahi-utils procps \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Same source apply_buttons_update() downloads from on a real device.
ARG BUTTONS_TARBALL_URL=https://github.com/dubpixel/dpx_buttonode/releases/download/buttons-deb-mirror/bitfocus-buttons-usb-relay-headless_0.1.0-beta.4_arm64.tar.gz

RUN curl -fsSL "$BUTTONS_TARBALL_URL" -o /tmp/buttons.tar.gz \
    && mkdir /tmp/buttons-extract \
    && tar -xzf /tmp/buttons.tar.gz -C /tmp/buttons-extract \
    && DEB="$(find /tmp/buttons-extract -name '*.deb' | head -1)" \
    && (dpkg -i "$DEB" || apt-get install -f -y) \
    && rm -rf /tmp/buttons.tar.gz /tmp/buttons-extract

EXPOSE 3040

# No systemd, so exec the relay process directly instead of via
# `systemctl start bitfocus-buttons-usb-relay`. The .deb's own postinst
# writes the actual binary path into the unit file it creates — pull it
# from there at image-build time rather than hardcoding a guess, so this
# stays correct if the package layout changes between releases.
RUN EXECSTART="$(grep -ohP '^ExecStart=\K.*' \
        /etc/systemd/system/bitfocus-buttons-usb-relay.service \
        /lib/systemd/system/bitfocus-buttons-usb-relay.service \
        2>/dev/null | head -1)"; \
    if [ -z "$EXECSTART" ]; then \
        echo "ERROR: no ExecStart found in the .deb's unit file — package layout changed, inspect manually" >&2; \
        exit 1; \
    fi; \
    echo "$EXECSTART" > /usr/local/bin/buttons-execstart

ENTRYPOINT ["/bin/sh", "-c", "exec $(cat /usr/local/bin/buttons-execstart)"]
