# dpx_buttonode Docker test infra

Two containers, deployed on the shared dev droplet (also used by other
projects — always deploy/teardown scoped with `-p dpx-buttonode` so this
never touches anything belonging to another project):

- **`companion`** — a real Bitfocus Companion instance. Gives a
  Satellite-mode dpx-buttonode unit something real to connect to, without a
  second physical device or a full-variant image build. Web UI + satellite
  protocol port, config persisted in a named volume.
- **`buttons`** — installs the mirrored Bitfocus Buttons `.deb` and runs
  its process. Regression-tests the install/update *mechanism* only (does
  the package still install, does the process start, does installing a
  newer `.deb` over it still work) — **not** real button/HID behavior,
  which needs actual hardware. Buttons and Satellite modes are already
  hardware-validated on real dpx-buttonode units; this container exists so
  the packaging/update path can be checked without needing that hardware
  every time.

The `buttons` image is pinned to `linux/arm64` (the mirrored `.deb` only
ships arm64 — there's no amd64 build) and needs QEMU emulation on an amd64
droplet. One-time host setup, run once per droplet:

```
docker run --privileged --rm tonistiigi/binfmt --install arm64
```

## Ports

Host ports are non-default to reduce collision risk with whatever else is
already running on the shared droplet:

| Container | Internal | Host |
|---|---|---|
| companion | 8000 (web UI) | 18000 |
| companion | 16622 (satellite protocol) | 26622 |
| buttons | 3040 (REST API) | 13040 |

**Before first deploy**, confirm these are actually free on the droplet
(`ss -ltn`). If any are taken, change the host-side port in
`docker-compose.yml` and update this table — don't silently reuse a port
something else owns.

## Deploy

From a checkout of this repo, on your workstation:

```
rsync -av --delete test/docker/ <droplet-user>@<droplet-host>:~/dpx-buttonode-test/
ssh <droplet-user>@<droplet-host> \
    "cd ~/dpx-buttonode-test && docker compose -p dpx-buttonode up -d --build"
```

(Droplet host/user go in this repo's gitignored `ACCESS.md` — not here.)

## Redeploy after a change

Same as deploy — `rsync` again, then re-run the same `up -d --build`. Compose
only rebuilds/recreates what actually changed.

## Point a real unit at the Companion container

In the dpx-buttonode web UI's Mode tab (Satellite mode), set the Companion
host/port to `<droplet-ip>` / `26622`. Confirm the unit shows up as a
connected surface in the Companion container's web UI at
`http://<droplet-ip>:18000`.

## Verify the buttons container

```
ssh <droplet-user>@<droplet-host> \
    "docker exec dpx-buttonode-buttons dpkg -s bitfocus-buttons-usb-relay-headless"
```

should report `Status: install ok installed`. Check the process itself with
`docker exec dpx-buttonode-buttons ps aux` (no systemd inside the container,
so `systemctl status` won't work here — that's expected).

## Teardown

```
ssh <droplet-user>@<droplet-host> \
    "cd ~/dpx-buttonode-test && docker compose -p dpx-buttonode down"
```

Add `-v` to also drop the `companion-config` volume (wipes persisted
Companion config) — only do this deliberately, not as a matter of routine.
This only ever touches containers/network/volumes under the `dpx-buttonode`
compose project — nothing belonging to another project on the shared box.
