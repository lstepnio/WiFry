# WiFry - IP Video Edition — Architecture

## System Overview

WiFry is a Raspberry Pi-based WiFi hotspot that simulates adverse network conditions for IP video (IPTV/STB) testing. STBs connect to WiFry's WiFi AP, and all their traffic passes through the RPi where it can be impaired, captured, and analyzed.

```
┌─────────────┐      WiFi        ┌──────────────────────────────┐     Ethernet    ┌──────────┐
│ STB / Client│ ◄──────────────► │       Raspberry Pi           │ ◄──────────────► │ Upstream │
│ Devices     │  (impaired path) │         (WiFry)              │  (clean uplink)  │ Network  │
└─────────────┘                  │                              │                   └──────────┘
                                 │  hostapd (WiFi AP)           │
                                 │  dnsmasq (DHCP + DNS)        │
                                 │  tc netem (impairments)      │
                                 │  mitmproxy (stream inspect)  │
                                 │  tshark (packet capture)     │
                                 │  FastAPI (backend API)       │
                                 │  React (frontend UI)         │
                                 └──────────────────────────────┘
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Network impairment | `tc netem` (delay, jitter, loss, corruption, reorder, bandwidth) |
| WiFi impairment | `hostapd_cli`, `iw` (band switch, TX power, deauth, rate limit) |
| WiFi AP | `hostapd` + `dnsmasq` |
| Packet capture | `tshark` (Wireshark CLI) |
| Stream analysis | `mitmproxy` (transparent HTTPS proxy for HLS/DASH inspection) |
| AI analysis | Anthropic Claude API / OpenAI API |
| HDMI capture | `ffmpeg` + `v4l2` (Elgato Cam Link 4K) |
| ADB | Android Debug Bridge (network mode) |
| VPN / Teleport | WireGuard, OpenVPN, IPsec/strongSwan |
| Backend | Python 3.11+ / FastAPI / uvicorn |
| Frontend | React 18 + TypeScript + Vite + Tailwind CSS |
| Sharing | Cloudflare Quick Tunnel, file.io |

## Session Workflow

The recommended workflow for IP video testing:

```
1. CREATE SESSION
   └─ Name it, tag it, optionally link ADB device
   └─ All subsequent artifacts auto-link to this session

2. CONFIGURE IMPAIRMENTS
   └─ Apply a profile (one-click: "Poor WiFi", "Satellite", etc.)
   └─ Or fine-tune: network sliders + WiFi impairments + Teleport VPN
   └─ Changes logged to session timeline automatically

3. CONNECT DEVICE (ADB)
   └─ Connect STB via network ADB
   └─ Start logcat (auto-correlated with session)
   └─ Take baseline screenshot

4. START CAPTURE
   └─ Configure BPF filters (host, port, protocol, or custom)
   └─ Capture runs as background tshark process
   └─ Auto-linked as session artifact

5. MONITOR STREAMS (if proxy enabled)
   └─ HLS/DASH manifests parsed in real-time
   └─ Track bitrate switches, buffer health, segment errors
   └─ Throughput ratio (≥1.33x = stable per TiVo spec)

6. ANALYZE
   └─ Stop capture → Run AI analysis
   └─ AI identifies retransmissions, latency issues, protocol errors
   └─ Results linked to session

7. COLLECT EVIDENCE
   └─ ADB screenshot, bugreport, dumpsys
   └─ HDMI frame capture (Cam Link 4K)
   └─ All saved on RPi, linked to session

8. GENERATE BUNDLE
   └─ One-click: zip all session artifacts + metadata
   └─ Includes: pcaps, analyses, screenshots, logcat, impairment timeline
   └─ SUMMARY.md with human-readable report

9. SHARE
   └─ Upload bundle to file.io (15min expiry, single download)
   └─ Or start Cloudflare Tunnel for live access
   └─ Collaboration mode: spectate or co-pilot
```

## Boot Sequence

```
1. systemd starts all services
2. wifry-recovery.service starts on tty2 (Alt+F2 for recovery console)
3. wifry-backend.service starts uvicorn
4. Lifespan startup:
   a. Apply fallback IP (169.254.42.1) on eth0 — ALWAYS, can't be disabled
   b. Check for boot profile → apply if found
   c. Otherwise: load saved config or use safe defaults
   d. Apply WiFi AP config (hostapd + dnsmasq)
   e. Apply Ethernet config (DHCP or static)
5. wifry-frontend.service serves the React build
```

## Recovery

If locked out (misconfigured WiFi/Ethernet):

1. **Fallback IP** (always works): Connect laptop to RPi Ethernet, navigate to `http://169.254.42.1:8080`
2. **Recovery console** (HDMI + keyboard): Press Alt+F2 → interactive menu with network reset, service restart, factory reset
3. **SSH** (if Ethernet works): `ssh pi@<rpi-ip>` → `sudo /opt/wifry/setup/wifry-recovery.sh`

## API Structure

All endpoints under `/api/v1/`:

| Prefix | Purpose | Key Endpoints |
|--------|---------|--------------|
| `/impairments` | tc netem control | GET, PUT /{iface}, DELETE |
| `/wifi-impairments` | WiFi-layer impairments | GET, PUT, DELETE |
| `/profiles` | Impairment presets | CRUD, POST /{name}/apply |
| `/sessions` | Test session correlation | CRUD, artifacts, bundles |
| `/captures` | Packet capture + AI | start, stop, analyze |
| `/streams` | HLS/DASH monitoring | list, detail, segments |
| `/adb` | Android device control | connect, shell, logcat, screencap |
| `/teleport` | VPN geo-shifting | profiles, connect, verify |
| `/hdmi` | HDMI capture | frame, record |
| `/wifi/scan` | WiFi environment | scan channels + networks |
| `/speedtest` | iperf3 speed test | run, results |
| `/tunnel` | Cloudflare tunnel | start, stop, status |
| `/fileio` | file.io upload | upload, bundle, history |
| `/collab` | Collaboration mode | status, mode, WebSocket |
| `/network-config` | WiFi AP + Ethernet config | current, apply, profiles |
| `/system` | RPi info + settings | info, storage, update, logs |
| `/annotations` | Notes + tags | CRUD |
| `/gremlin` | Chaos mode (easter egg) | activate, deactivate (hidden) |

## File Structure

```
WiFry/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI app, lifespan, routers
│   │   ├── config.py                  # Settings (pydantic-settings)
│   │   ├── routers/                   # API endpoints (15 routers)
│   │   ├── services/                  # Business logic (20+ services)
│   │   ├── models/                    # Pydantic models
│   │   ├── utils/shell.py             # Safe async subprocess wrapper
│   │   └── mitmproxy_addon/           # HLS/DASH stream interception
│   ├── profiles/                      # Built-in impairment profiles (12)
│   └── tests/                         # pytest test suite
├── frontend/
│   ├── src/
│   │   ├── App.tsx                    # Root with ErrorBoundary
│   │   ├── components/                # 25+ React components
│   │   ├── hooks/                     # useApi, useNotification
│   │   ├── api/client.ts              # Typed API client
│   │   └── types/index.ts             # TypeScript interfaces
│   └── index.html                     # Dark mode forced
├── setup/
│   ├── install.sh                     # One-shot RPi setup
│   ├── wifry-recovery.sh             # Physical access recovery
│   ├── wifry-motd.sh                 # Login banner
│   ├── *.service                      # systemd units
│   └── *.template                     # hostapd/dnsmasq configs
└── ARCHITECTURE.md                    # This file
```
