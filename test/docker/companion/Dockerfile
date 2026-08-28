# Runs a real Bitfocus Companion instance in a container so a
# dpx-buttonode unit in Satellite mode has something real to connect to,
# without needing a second physical device or a full-variant image build.
#
# Uses the exact official installer (bitfocus/companion-pi's install.sh —
# same one scripts/install-companion.sh runs) rather than reimplementing
# it, so this stays in sync with what the real image actually installs.
# The only incompatibility is systemd: install.sh calls `systemctl enable
# companion` and update.sh calls `systemctl daemon-reload`, neither of
# which exist in a container. A no-op `systemctl` stub ahead of the real
# one on PATH absorbs both calls harmlessly — everything else about the
# install (dependency list, git clone of companionpi, the actual
# node/main.js build) runs unmodified.
#
# At runtime, exec companionpi's own launch.sh directly instead of via
# systemd — it's already a plain, systemd-independent launcher (see
# https://github.com/bitfocus/companion-pi/blob/main/launch.sh), just run
# as the `companion` user install.sh created instead of through a unit
# file.
FROM debian:bookworm-slim

RUN printf '#!/bin/sh\necho "[systemctl stub] ignoring: $*"\nexit 0\n' \
        > /usr/local/bin/systemctl \
    && chmod +x /usr/local/bin/systemctl

RUN apt-get update -q && apt-get install -yq --no-install-recommends \
        git zip unzip curl ca-certificates sudo iproute2 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL \
        https://raw.githubusercontent.com/bitfocus/companion-pi/main/install.sh \
        -o /tmp/companion-install.sh \
    && chmod +x /tmp/companion-install.sh \
    && COMPANION_BUILD=stable /tmp/companion-install.sh \
    && rm -f /tmp/companion-install.sh

# Web UI
EXPOSE 8000
# Satellite protocol — see get_satellite_config() in dpx-buttonode-ui.py
EXPOSE 16622

WORKDIR /usr/local/src/companionpi
USER companion
ENTRYPOINT ["/usr/local/src/companionpi/launch.sh"]
