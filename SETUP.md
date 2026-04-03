# WiFry - IP Video Edition — RPi Setup Guide

## Prerequisites

### Hardware
- **Raspberry Pi 4B+ or 5** (4GB+ RAM recommended)
- **MicroSD card** (32GB+ recommended, Class 10 / A2)
- **Ethernet cable** connected to your upstream network
- **Power supply** (USB-C, 5V 3A for RPi 4, 5V 5A for RPi 5)

### Optional Hardware
- **Elgato Cam Link 4K** — for HDMI capture from STBs (enable via feature flag)
- **USB WiFi adapter** — if you need a second WiFi interface
- **HDMI monitor + USB keyboard** — for physical access recovery

---

## Deployment Methods

### Method 1: Pre-built Image (Recommended for field deployment)

The fastest way. Download a pre-built image with WiFry fully installed.

1. Download the latest `wifry-<version>-rpi-arm64.img.xz` from GitHub Releases
2. Flash to SD card using [Raspberry Pi Imager](https://www.raspberrypi.com/software/):
   - Choose **"Use custom"** and select the downloaded `.img.xz` file
   - No need to configure anything — WiFry defaults are pre-baked
3. Insert SD card, connect Ethernet, power on
4. Wait ~60 seconds for first boot
5. Done — connect to WiFi `WiFry` (password: `wifry1234`)

**Default credentials:**
| Service | Value |
|---------|-------|
| WiFi SSID | `WiFry` |
| WiFi Password | `wifry1234` |
| SSH user | `pi` |
| SSH password | `wifry` |
| Web UI (WiFi) | http://192.168.4.1:3000 |
| Web UI (Ethernet) | http://\<rpi-ip\>:8080 |
| Fallback IP | http://169.254.42.1:8080 |

> **First login**: WiFry shows a configuration banner encouraging you to change the WiFi SSID/password and set up your environment.

### Method 2: Deploy from Laptop (Recommended for development)

Build on your fast laptop, deploy to a fresh RPi OS install.

```bash
# On your laptop:
git clone <repo-url> WiFry && cd WiFry
make install          # One-time: install local dev dependencies
make deploy-ssh RPI=pi@<rpi-ip>   # Build + deploy (~10 min first time)
```

### Method 3: Direct Install on RPi

```bash
# SSH into RPi running Raspberry Pi OS Bookworm 64-bit:
git clone <repo-url> /tmp/wifry
cd /tmp/wifry
sudo bash setup/install.sh
```

---

## Building Custom Images

For teams that need to distribute WiFry to multiple RPis:

```bash
# On a Linux build machine (or CI):
cd image-build
./build-image.sh 1.0.0
# Output: image-build/output/wifry-1.0.0-rpi-arm64.img.xz
```

Or use GitHub Actions — push a tag to build automatically:
```bash
git tag v1.0.0
git push origin v1.0.0
# → GitHub Actions builds image and creates a Release with download link
```

The image builder uses [pi-gen](https://github.com/RPi-Distro/pi-gen) (the official Raspberry Pi OS build tool) with a custom stage that installs all WiFry dependencies, code, and configuration.

---

## Step 1: Flash and Boot

### Using pre-built image:
1. Flash `wifry-*.img.xz` to SD card via RPi Imager
2. Insert, connect Ethernet, power on
3. Wait 60 seconds

### Using RPi OS + deploy:
1. Flash RPi OS Bookworm 64-bit (enable SSH in Imager settings)
2. Boot, connect Ethernet
3. From laptop: `make deploy-ssh RPI=pi@<rpi-ip>`
4. Flash to your SD card
5. Insert SD card into RPi, connect Ethernet, boot

## Step 2: Find Your RPi's IP

```bash
# Option A: Check your router's DHCP table for "wifry"

# Option B: Scan the network
ping wifry.local

# Option C: If you have a monitor attached, it shows on screen
```

## Step 3: Deploy WiFry

### Method A: From Your Laptop (Recommended)

This builds the frontend on your fast laptop and deploys to the RPi:

```bash
# Clone the repo on your laptop
git clone <repo-url> WiFry
cd WiFry

# Install local dev dependencies (one-time)
make install

# Deploy to RPi (builds frontend, syncs, installs everything)
make deploy-ssh RPI=pi@<rpi-ip>
```

The install takes ~10-15 minutes on first run (downloads packages, sets up venv).

### Method B: Directly on the RPi

```bash
# SSH into the RPi
ssh pi@<rpi-ip>

# Clone and install
git clone <repo-url> /tmp/wifry
cd /tmp/wifry
sudo bash setup/install.sh
```

⚠️ This is slower because the frontend builds on the RPi (~5-10 min).

## Step 4: Verify Installation

The install script runs verification checks automatically. You should see:

```
  ✓ Backend API responding
  ✓ Frontend built
  ✓ hostapd running
  ✓ dnsmasq running
  ✓ WiFi AP IP set
  ✓ IP forwarding enabled
  ✓ NAT rules set
  ✓ tshark available
  ✓ ffmpeg available
  ✓ CoreDNS available
  ✓ Recovery console enabled
```

Or verify manually from your laptop:

```bash
make verify-ssh RPI=pi@<rpi-ip>
```

## Step 5: Connect

### Via WiFi (STBs connect here)
- **SSID**: `WiFry`
- **Password**: `wifry1234`
- **Web UI**: http://192.168.4.1:3000

### Via Ethernet (from your laptop)
- **Web UI**: http://\<rpi-ip\>:8080
- **API Docs**: http://\<rpi-ip\>:8080/docs

### Fallback (if everything else fails)
- Connect laptop directly to RPi's Ethernet port
- Navigate to: http://169.254.42.1:8080

### Physical Recovery
- Plug in HDMI monitor + USB keyboard
- Press **Alt+F2** for the recovery console

---

## Quick Reference

### Day-to-Day Commands

```bash
# Check status
make status-ssh RPI=pi@<rpi-ip>

# View live logs
make logs-ssh RPI=pi@<rpi-ip>

# Quick update (code change, no full reinstall)
make update-ssh RPI=pi@<rpi-ip>

# Restart services
make restart-ssh RPI=pi@<rpi-ip>

# Full redeploy
make deploy-ssh RPI=pi@<rpi-ip>
```

### On the RPi

```bash
# Backend logs
journalctl -u wifry-backend -f

# Frontend logs
journalctl -u wifry-frontend -f

# All WiFry logs
journalctl -u wifry-backend -u wifry-frontend -u hostapd -u dnsmasq -f

# Restart everything
sudo systemctl restart wifry-backend wifry-frontend hostapd dnsmasq

# Recovery console
sudo /opt/wifry/setup/wifry-recovery.sh
```

### Default Credentials
| Service | Credential |
|---------|-----------|
| WiFi SSID | `WiFry` |
| WiFi Password | `wifry1234` |
| Web UI | No password (set one in Settings > App Settings) |
| SSH | Whatever you configured during OS flash |

---

## Architecture on the RPi

```
/opt/wifry/                    # Application code
  ├── backend/                 # Python FastAPI + uvicorn
  │   ├── .venv/               # Python virtual environment
  │   └── app/                 # Application code
  ├── frontend/
  │   └── dist/                # Built React app (served by Python http.server)
  └── setup/                   # Install scripts, systemd units, recovery

/var/lib/wifry/                # Runtime data (survives updates)
  ├── captures/                # Packet capture .pcap files
  ├── sessions/                # Session metadata + artifacts
  ├── reports/                 # Generated HTML reports
  ├── bundles/                 # Support bundle .zip files
  ├── adb-files/               # ADB screenshots, bugreports
  ├── coredns/                 # CoreDNS Corefile + hosts
  ├── teleport/                # VPN profiles
  ├── network-profiles/        # Saved network configurations
  ├── settings.json            # App settings
  ├── network_config.json      # WiFi AP + Ethernet config
  └── feature_flags.json       # Feature flag overrides

/etc/hostapd/hostapd.conf      # WiFi AP config
/etc/dnsmasq.d/wifry.conf      # DHCP + DNS config
/etc/sudoers.d/wifry            # Permissions for wifry user
```

### Systemd Services
| Service | Port | Purpose |
|---------|------|---------|
| `wifry-backend` | 8080 | FastAPI REST API |
| `wifry-frontend` | 3000 | React web UI (http.server) |
| `wifry-recovery` | tty2 | Physical recovery console |
| `hostapd` | — | WiFi access point |
| `dnsmasq` | 53 | DHCP + DNS |

---

## Troubleshooting

### WiFi AP not starting
```bash
# Check hostapd status
sudo systemctl status hostapd
sudo journalctl -u hostapd -n 50

# Common fix: unmask hostapd
sudo systemctl unmask hostapd
sudo systemctl restart hostapd
```

### Can't reach Web UI
1. Try the fallback IP: http://169.254.42.1:8080
2. Or use recovery console (Alt+F2)
3. Check if backend is running: `systemctl status wifry-backend`

### STB can't connect to WiFi
1. Check hostapd is running: `systemctl status hostapd`
2. Check the WiFi interface is up: `ip link show wlan0`
3. Check DHCP: `journalctl -u dnsmasq -n 20`

### Backend crashes on startup
```bash
# Check the error
journalctl -u wifry-backend -n 50

# Common fix: recreate venv
sudo rm -rf /opt/wifry/backend/.venv
sudo -u wifry python3 -m venv /opt/wifry/backend/.venv
sudo -u wifry /opt/wifry/backend/.venv/bin/pip install -r /opt/wifry/backend/requirements.txt
sudo systemctl restart wifry-backend
```

### Factory reset (keep code, wipe data)
```bash
sudo rm -rf /var/lib/wifry/*
sudo systemctl restart wifry-backend wifry-frontend
```

### Complete reinstall
```bash
make deploy-ssh RPI=pi@<rpi-ip>
```
