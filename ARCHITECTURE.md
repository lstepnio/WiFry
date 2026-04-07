# WiFry - IP Video Edition — Architecture

## System Overview

WiFry is a Raspberry Pi-based WiFi hotspot that simulates adverse network conditions for IP video (IPTV/STB) testing. STBs connect to WiFry's WiFi AP, and all their traffic passes through the RPi where it can be impaired, captured, and analyzed. In production, a single FastAPI process serves both the REST API and the built React UI on port `8080`.

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
| Frontend | React 19 + TypeScript + Vite + Tailwind CSS |
| Sharing | Session bundle links via `file.io`; experimental live access via Cloudflare Quick Tunnel |

## Product Surface

WiFry intentionally keeps the day-to-day operator workflow narrow:

- **Supported workflow:** configure connectivity in **Network Config**, create a **Session**, collect artifacts into that session, then generate or share a session bundle.
- **Experimental / opt-in:** **Live Remote Access** (Cloudflare Quick Tunnel) and **Collaboration Mode**. These are hidden behind feature flags and grouped under System rather than treated as the default sharing path.
- **Backend-only compatibility surface:** **Scenario APIs** remain available for automation/testing, but they are not part of the supported primary UI workflow.

## Deployment Model

WiFry currently runs in two distinct modes:

| Mode | UI delivery | API delivery | Ports |
|------|-------------|--------------|-------|
| Local development | Vite dev server | FastAPI / uvicorn | `3000` for Vite, `8080` for FastAPI |
| Raspberry Pi / production | Built frontend from `frontend/dist`, served by FastAPI | FastAPI / uvicorn | `8080` |

Important implication: there is no separate `wifry-frontend` runtime service in the current appliance model. If a stale note or old script mentions one, treat `wifry-backend` as the source of truth for the web UI.

## Runtime State Boundaries

WiFry now treats critical runtime state in two explicit buckets so restart behavior is predictable:

| State | Boundary | Restart Behavior |
|-------|----------|------------------|
| Session records, artifact metadata | Persistent on disk | Restored |
| Active session pointer for auto-linking | Persistent on disk | Restored |
| Capture metadata / AI analysis results | Persistent on disk | Restored |
| Collaboration mode (`co-pilot` vs `download`) | Persistent on disk | Restored |
| Live tshark subprocess handles | In memory only | Not restored; stale `running` captures are reconciled to `error` |
| Connected collaboration users / shared navigation state | In memory only | Not restored; clients reconnect and resync |
| Cloudflare tunnel process and public URL | In memory only | Not restored; operator must restart the tunnel |

This keeps durable operator intent and artifact inventory on disk without pretending that live process handles, WebSockets, or public tunnel URLs can be safely recovered after a backend restart.

## Observability Foundation

WiFry now ships with a minimal observability layer aimed at release support rather than heavy telemetry infrastructure:

| Signal | Behavior |
|-------|----------|
| Request correlation | Every HTTP response includes `X-Request-ID`; the same ID is attached to backend log lines created during that request |
| Structured logs | Backend logs are emitted as JSON lines with stable fields such as `ts`, `level`, `logger`, `message`, `request_id`, and event-specific metadata |
| Audit events | Destructive or external actions append JSONL audit events under `/var/lib/wifry/logs/audit.log.jsonl` |
| Operator diagnostics | `/api/v1/system/audit` exposes recent audit events without having to parse journal output |
| Support bundle diagnostics | Session bundles include a narrow `diagnostics/bundle_diagnostics.json` manifest about bundle assembly only |

This keeps the Pi-friendly deployment simple: logs stay local, audit events are append-only JSONL, and operators can correlate UI actions and API calls with one request ID without turning the Session bundle into a WiFry appliance-support export.

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
   └─ Includes a narrow bundle-assembly manifest (for missing files / packaging traceability)
   └─ SUMMARY.md with human-readable report

9. SHARE
   └─ Supported: generate an expiring support-bundle link from the Session detail view
   └─ Experimental: start Cloudflare Tunnel for live remote access
   └─ Experimental: enable collaboration mode only for temporary co-pilot sessions
```

## Boot Sequence

```
1. systemd starts all services
2. wifry-recovery.service starts on tty2 (Alt+F2 for recovery console)
3. wifry-backend.service starts uvicorn on port 8080
4. Lifespan startup:
   a. Apply fallback IP (169.254.42.1) on eth0 — ALWAYS, can't be disabled
   b. Check for boot profile → apply if found
   c. Otherwise: load saved config or use safe defaults
   d. Apply WiFi AP config (hostapd + dnsmasq)
   e. Apply Ethernet config (DHCP or static)
5. If `frontend/dist` is present, FastAPI serves the built React app from the same origin as the API
```

## Recovery

If locked out (misconfigured WiFi/Ethernet):

1. **Fallback IP** (always works): Connect laptop to RPi Ethernet, navigate to `http://169.254.42.1:8080`
2. **Recovery console** (HDMI + keyboard): Press Alt+F2 → interactive menu with network reset, service restart, factory reset
3. **SSH** (if Ethernet works): `ssh pi@<rpi-ip>` → `sudo /opt/wifry/setup/wifry-recovery.sh`

Operationally, the services that matter for box reachability are `wifry-backend`, `hostapd`, and `dnsmasq`.

## API Structure

All endpoints under `/api/v1/`:

| Prefix | Purpose | Key Endpoints |
|--------|---------|--------------|
| `/impairments` | tc netem control | GET, PUT /{iface}, DELETE |
| `/wifi-impairments` | WiFi-layer impairments | GET, PUT, DELETE |
| `/profiles` | Impairment presets | CRUD, POST /{name}/apply |
| `/scenarios` | Automated scenario runs | experimental/backend-only CRUD + run endpoints |
| `/sessions` | Test session correlation | CRUD, artifacts, bundles |
| `/captures` | Packet capture + AI | start, stop, analyze |
| `/streams` | HLS/DASH monitoring | list, detail, segments |
| `/adb` | Android device control | connect, shell, logcat, screencap |
| `/teleport` | VPN geo-shifting | profiles, connect, verify |
| `/hdmi` | HDMI capture | frame, record |
| `/wifi/scan` | WiFi environment | scan channels + networks |
| `/speedtest` | iperf3 speed test | run, results |
| `/tunnel` | Live remote access | experimental start, stop, status |
| `/fileio` | Bundle link generation | expiring uploads + history |
| `/collab` | Collaboration mode | experimental status, mode, WebSocket |
| `/network-config` | WiFi AP + Ethernet config | current, apply, profiles |
| `/system` | RPi info + settings | info, storage, update, logs, audit |
| `/annotations` | Notes + tags | CRUD |
| `/gremlin` | Chaos mode (easter egg) | activate, deactivate (hidden) |

## File Structure

```
WiFry/
├── README.md                        # Human onboarding entrypoint
├── CONTRIBUTING.md                  # Contributor setup + validation
├── RUNBOOKS.md                      # Install/update/recovery/security runbooks
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app, lifespan, SPA serving
│   │   ├── config.py                # Settings (pydantic-settings)
│   │   ├── routers/                 # API routers
│   │   ├── services/                # Business logic and hardware integrations
│   │   ├── models/                  # Pydantic models
│   │   ├── utils/shell.py           # Safe async subprocess wrapper
│   │   └── mitmproxy_addon/         # HLS/DASH stream interception
│   ├── profiles/                    # Built-in impairment profiles
│   └── tests/                       # pytest suite
├── frontend/
│   ├── src/
│   │   ├── App.tsx                  # Root app shell
│   │   ├── components/              # Operator panels and shell
│   │   ├── hooks/                   # Data and notification hooks
│   │   ├── api/client.ts            # Typed API client
│   │   └── types/index.ts           # TypeScript interfaces
│   └── dist/                        # Production build served by FastAPI
├── setup/
│   ├── install.sh                   # One-shot RPi setup
│   ├── wifry-backend.service        # Production service
│   ├── wifry-recovery.sh            # Physical access recovery
│   ├── wifry-recovery.service       # Recovery console launcher
│   └── *.template                   # hostapd/dnsmasq configs
└── ARCHITECTURE.md                  # This file
```
