# WiFry Setup Guide

This guide describes how to install, deploy, and verify WiFry based on the current code and scripts in this repo.

## Current Runtime Truth

- On a deployed box, `wifry-backend` serves both the API and the built frontend on port `8080`
- The production UI is served from `frontend/dist` by FastAPI
- Local frontend development still uses Vite on port `3000`
- The supported operator flow is `Network Config -> Session -> Bundle/Share`
- Live remote access and collaboration are experimental

Use [RUNBOOKS.md](RUNBOOKS.md) for day-two operations such as updates, recovery, and security checks.

The examples below use `pi@wifry.local`. Substitute the current Pi IP if mDNS does not resolve on your network.

## Prerequisites

### Hardware

- Raspberry Pi 4B or 5
- 32 GB+ microSD card recommended
- Ethernet connection to an upstream network
- Power supply suitable for the Pi model

### Optional hardware

- HDMI monitor + USB keyboard for local recovery
- USB WiFi adapter if you need additional wireless hardware
- Elgato Cam Link 4K for HDMI capture workflows

## Deployment Methods

### Method 1: release image

If a release includes a Raspberry Pi image artifact, flash that image and then verify the box using the commands below. Exact defaults for SSH credentials and first-boot behavior should come from the release notes for that tag, not from stale assumptions in older docs.

### Method 2: deploy from a laptop

This is the most practical development path.

```bash
git clone <repo-url> WiFry
cd WiFry
make install
make deploy-ssh RPI=pi@wifry.local
```

This path builds the frontend locally, syncs the repo to the Pi, and runs `setup/install.sh`.

### Method 3: direct install on the Pi

```bash
git clone <repo-url> /tmp/wifry
cd /tmp/wifry
sudo bash setup/install.sh
```

This is slower because the frontend build runs on the Pi.

## Verify the Installation

After install, verify the current service set and the backend health endpoint:

```bash
ssh pi@wifry.local "sudo systemctl status wifry-backend hostapd dnsmasq --no-pager"
ssh pi@wifry.local "curl -sf http://localhost:8080/api/v1/health"
ssh pi@wifry.local "curl -sf http://localhost:8080/api/v1/system/dependencies | python3 -m json.tool"
```

You should also confirm the built frontend exists:

```bash
ssh pi@wifry.local "test -f /opt/wifry/frontend/dist/index.html && echo frontend-ok"
```

## Access Paths

### WiFi AP

- SSID default: `WiFry`
- Password default: `wifry1234`
- UI: [http://192.168.4.1:8080](http://192.168.4.1:8080)

### Ethernet

- UI: [http://<rpi-ip>:8080](http://<rpi-ip>:8080)
- API docs: [http://<rpi-ip>:8080/docs](http://<rpi-ip>:8080/docs)

### Recovery fallback

- Direct Ethernet recovery IP: [http://169.254.42.1:8080](http://169.254.42.1:8080)
- Physical console: `Alt+F2`

## First-Run Operator Flow

Once the box is reachable, use this order in the UI:

1. `System > Network Config` to set WiFi AP, Ethernet uplink, and any reusable boot profile
2. `Sessions` to create a session before collecting captures or device artifacts
3. `Session detail > Generate Bundle` or `Bundle + Share` to hand off STB/test evidence

Experimental surfaces:

- `System > Remote Access` for Cloudflare tunnel and collaboration
- Scenario APIs for automation only

## Day-to-Day Commands

### Local development

```bash
make dev
make backend
make frontend
```

### Remote box management

```bash
make status-ssh RPI=pi@wifry.local
make logs-ssh RPI=pi@wifry.local
make update-ssh RPI=pi@wifry.local
make restart-ssh RPI=pi@wifry.local
make verify-ssh RPI=pi@wifry.local
```

### Directly on the Pi

```bash
sudo systemctl status wifry-backend hostapd dnsmasq --no-pager
sudo journalctl -u wifry-backend -u hostapd -u dnsmasq -f
sudo /opt/wifry/setup/wifry-recovery.sh
```

## Files and Paths on the Pi

```text
/opt/wifry/
  backend/                     FastAPI app and Python environment
  frontend/dist/               Built frontend served by FastAPI
  setup/                       Install scripts, systemd units, recovery tools
  VERSION                      Current installed version tag/string

/var/lib/wifry/
  captures/                    Packet captures
  sessions/                    Session metadata and artifacts
  bundles/                     Generated session bundles
  reports/                     Generated reports
  adb-files/                   Screenshots, bugreports, and similar artifacts
  network-profiles/            Saved network configuration profiles
  scenarios/                   Saved scenario definitions
  logs/                        Audit log and related diagnostics
  settings.json                App settings
  network_config.json          Applied network configuration
  feature_flags.json           Feature overrides
```

## System Services

| Service | Purpose | Port |
|---------|---------|------|
| `wifry-backend` | FastAPI API plus built frontend | `8080` |
| `wifry-recovery` | Recovery console on `tty2` | n/a |
| `hostapd` | WiFi AP | n/a |
| `dnsmasq` | DHCP and DNS for the AP | `53` |

There is no separate `wifry-frontend` production service in the current repo state.

## Troubleshooting

### UI does not load

```bash
ssh pi@wifry.local "sudo systemctl status wifry-backend --no-pager"
ssh pi@wifry.local "curl -sf http://localhost:8080/api/v1/health"
ssh pi@wifry.local "sudo journalctl -u wifry-backend -n 100 --no-pager"
```

### WiFi AP is down

```bash
ssh pi@wifry.local "sudo systemctl status hostapd dnsmasq --no-pager"
ssh pi@wifry.local "sudo journalctl -u hostapd -u dnsmasq -n 100 --no-pager"
ssh pi@wifry.local "ip addr show wlan0"
```

### Box is reachable only over direct Ethernet

Use [http://169.254.42.1:8080](http://169.254.42.1:8080) or run the recovery console:

```bash
ssh pi@wifry.local "sudo /opt/wifry/setup/wifry-recovery.sh"
```

### Need a production image

Image builds are driven from tags and the GitHub Actions workflow in `.github/workflows/build-image.yml`. Before trusting a given image in the field, verify the release notes and do a real-box boot test for that tag.
