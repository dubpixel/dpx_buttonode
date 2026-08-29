# Mock Data Reference

Hardcoded values to use when building static HTML previews from the Python source.
Keep these consistent across all 6 tab files.

## Device Values

| Field | Value |
|---|---|
| Hostname | `dpx-buttonode-8A2F` |
| IP | `10.50.0.44` |
| IP/CIDR | `10.50.0.44/22` |
| MAC | `e4:5f:01:8a:2f:b1` |
| Gateway | `10.50.0.1` |
| DNS | `8.8.8.8` |
| Network mode | DHCP |
| mDNS | active |
| Primary iface | `end0` |

## Mode & Services

| Field | Value |
|---|---|
| dpx-mode | `buttons` |
| Buttons service | active (green) |
| Satellite service | inactive (grey) |
| Satellite host | *(empty)* |
| Satellite port | `16622` |
| Buttons API | reachable on `:3040` |

## USB Devices

```
Bus 001 Device 003: ID 0fd9:0060 Elgato Systems GmbH Stream Deck MK.2
Bus 001 Device 002: ID 0424:2514 Microchip Technology, Inc. USB 2.0 Hub
Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub
```

Stream Deck USB path: `1-1.2`

## Nodes

| Node | IP | Self? |
|---|---|---|
| `dpx-buttonode-8A2F` | `10.50.0.44` | yes |
| `dpx-buttonode-3C1A` | `10.50.0.51` | no |
| `dpx-buttonode-F07E` | `10.50.0.67` | no |

## Build Info (footer)

| Field | Value |
|---|---|
| dpx_version | `0.5.0` |
| buttons_version | `0.1.0-beta.4` |
| satellite_version | `1.9.1` |
| git_branch | `main` |
| git_commit | `a3f7c12` |
| build_date | `2026-07-17` |

---

## Python Source Symbol Map

Where to find each piece in `src/dpx-buttonode-ui/dpx-buttonode-ui.py`:

| Symbol | Approx lines | Notes |
|---|---|---|
| `CSS` | 343–383 | Paste verbatim into `<style>`. Remove `min-height:100vh` from the `body` rule. |
| `page()` | 386–426 | Page shell — header, nav tabs, footer. |
| `render_status()` | 431–476 | Status tab |
| `render_hostname()` | 477–500 | Hostname tab |
| `render_network()` | 501–549 | Network tab |
| `render_devices()` | 550–591 | Devices tab |
| `render_nodes()` | 592–700 | Nodes tab |
| `render_mode()` | 701–785 | Mode tab |
