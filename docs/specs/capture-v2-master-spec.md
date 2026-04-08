# Packet Capture v2 — Master Specification

**Status:** Draft — Definitive Reference
**Date:** 2026-04-07
**Target:** WiFry v0.2.x (MVP), v0.3.x (Next), v0.4+ (Roadmap)
**Supersedes:** `capture-v2-spec.md`, `capture-v2-ux-spec.md`, `ai-analysis-framework.md`, `rpi5-performance-guide.md`

This document consolidates the complete design for WiFry's packet capture system v2: product vision, UX, backend architecture, AI framework, RPi 5 optimization, and implementation plan. It is the single source of truth for building the feature.

---

# Part I — Product & Workflow

## 1. Product Vision and Design Principles

### What We're Building

WiFry's capture module transforms from a thin `tshark -w` wrapper into a guided troubleshooting workflow. The user picks a purpose ("why is the video buffering?"), the system runs a focused capture with appropriate filters, automatically extracts structured statistics, and optionally calls AI for interpretation. The entire pipeline is designed to work within a Raspberry Pi 5's 8 GB RAM and SD card budget.

### Current Gaps

| Gap | Impact |
|-----|--------|
| No rolling capture — must decide "start" before the problem occurs | Misses transient issues; user must reproduce the fault |
| No capture size/time rotation | SD card fills up on long runs |
| No concurrent capture limit | Multiple tshark processes can OOM the RPi |
| AI receives raw tshark stat dumps truncated to 3000 chars | Analysis quality degrades on large captures; no structure |
| No purpose-driven capture modes | User must know BPF syntax to filter for DNS, streaming, etc. |
| No automatic retention policy | Old captures accumulate until manual delete or factory reset |
| Single flat pcap per capture | Can't preserve a window around an event without keeping everything |

### Design Principles

1. **Capture always, analyze selectively.** The system should be recording before the user knows there's a problem.
2. **Extract small, send small.** AI never sees raw pcap. It sees structured statistical summaries (~5 KB).
3. **RPi-first.** Every design choice assumes 8 GB RAM, quad-core ARM, and a 32-128 GB SD card.
4. **One-click troubleshooting.** The common case: pick a mode, hit start, get a diagnosis.
5. **Stats free, AI on-demand.** Every capture produces a useful stats dashboard without any AI key. AI interpretation is a paid bonus layer.
6. **Evidence, not assertions.** Every AI finding cites specific data. Confidence is categorical (HIGH/MEDIUM/LOW), never fake percentages.

---

## 2. Recommended User Workflows

### 2.1 Primary Workflow: Quick Capture

```
[1] User opens Captures tab
         |
[2] Sees 5 "Quick Capture" cards:
    - Connectivity Check
    - DNS Troubleshoot
    - HTTPS / Web
    - Streaming / Video
    - Security Scan
         |
[3] Picks "Streaming / Video"
         |
[4] Card expands inline — user sees:
    - Duration: [120s] (adjustable)
    - Interface: [wlan0]
    - BPF: tcp port 80 or tcp port 443 or udp portrange 1024-65535 (read-only)
    - Ring buffer: 10 × 10 MB segments (read-only)
         |
[5] Clicks [Start]
         |
[6] Capture runs. UI shows in Active zone:
    - Live file size + estimated packet rate
    - Elapsed time / remaining time with progress bar
    - Ring buffer segment indicator (e.g., "Segment 3/10")
         |
[7] User stops (or duration expires)
         |
[8] Post-processing pipeline runs automatically (~15-30s):
    a. Merge ring buffer segments into single pcap
    b. Extract pack-specific statistics via tshark
    c. Run deterministic interest detection (threshold checks)
    d. Build structured summary JSON
    e. Enforce retention policy
         |
[9] Capture appears in History zone with inline stats and health badge
         |
[10] User clicks [View Details] → Stats dashboard (no AI needed)
     Or clicks [Get AI Diagnosis] → AI interpretation (~$0.01-0.03)
```

### 2.2 Custom Capture Workflow

For users who know their BPF, need specific limits, or want to capture traffic that doesn't fit a pack. Accessed via "Custom Capture" link below the pack cards. Exposes the full form: interface, name, host/port/protocol filters, custom BPF, duration, max size, ring buffer toggle, segment configuration.

### 2.3 Session-Linked Capture Workflow

When a test session is active, captures auto-link as session artifacts. The Session detail view shows a timeline correlating capture events with impairment changes:

```
Timeline:
  14:30  Session started
  14:31  Capture started — Streaming / Video (capture-a1b2)
  14:31  Impairment applied — 3G Congested (100ms delay, 2% loss)
  14:33  Capture completed — Retx: 1.4%, Throughput: 2.5 Mbps
  14:34  Impairment cleared
  14:35  Capture started — Streaming / Video (capture-c3d4)
  14:37  Capture completed — Retx: 0.2%, Throughput: 5.1 Mbps
```

### 2.4 Background Capture (Phase 2)

A persistent ring-buffer capture that runs whenever the AP is active. When the user notices an issue, they click "Preserve last 60s" to snapshot the ring buffer into a named capture for analysis. This means the system was already recording before the problem occurred.

### 2.5 Comparative Analysis (Phase 2)

Select two completed captures (e.g., before/after impairment) and click "Compare." The system pre-computes numeric deltas and sends both summaries to AI in a single call for explanation.

---

## 3. UX Redesign

### 3.1 Three-Zone Layout

The Captures tab transforms from a single flat list into three distinct zones:

```
┌─────────────────────────────────────────────────────────────────┐
│  CAPTURES TAB                                                   │
│                                                                 │
│  ┌─ Zone A: Start ────────────────────────────────────────────┐ │
│  │  5 Quick Capture cards + "Custom Capture" link             │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌─ Zone B: Active ───────────────────────────────────────────┐ │
│  │  Running capture(s) with live progress — 0-2 items         │ │
│  │  (hidden when no captures running)                         │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌─ Zone C: History ──────────────────────────────────────────┐ │
│  │  Completed captures with inline stats + drill-in           │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Pack Card Grid (Zone A)

Five cards in a horizontal scrollable row (mobile) or 2-3 column grid (desktop):

```
┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐
│Connectiv. │ │   DNS     │ │HTTPS/Web  │ │Streaming  │ │ Security  │
│Can you    │ │Are lookups│ │Are web    │ │Why is the │ │Is there   │
│reach the  │ │fast and   │ │requests   │ │video      │ │unexpected │
│network?   │ │correct?   │ │completing?│ │buffering? │ │traffic?   │
│   30s     │ │   60s     │ │   60s     │ │   120s    │ │   60s     │
└───────────┘ └───────────┘ └───────────┘ └───────────┘ └───────────┘
                           Custom Capture →
```

Clicking a card expands an inline config bar below it (not a modal):

```
┌──────────────────────────────────────────────────┐
│  Streaming / Video                     [Start]   │
│  Duration: [120s ▾]   Interface: [wlan0 ▾]       │
│  BPF: tcp port 80 or tcp port 443 or udp ...     │
│  Ring buffer: 10 × 10 MB segments                │
│                                    [Cancel]       │
└──────────────────────────────────────────────────┘
```

Only Duration and Interface are editable. BPF and ring buffer are shown as read-only context.

When at max concurrent captures (2), cards show a dimmed state with tooltip: "Stop a running capture to start a new one."

### 3.3 Active Capture Card (Zone B)

```
┌──────────────────────────────────────────────────┐
│  ● Recording    Streaming / Video                │
│  wlan0 · tcp port 80 or tcp port 443 or udp...   │
│                                                  │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░  54s / 120s        │
│                                                  │
│  12.4 MB captured · Segment 3/10 · ~2,100 pkt/s │
│                                          [Stop]  │
└──────────────────────────────────────────────────┘
```

- Pulsing green dot + "Recording" (matches SessionPanel pattern)
- Progress bar with elapsed/total
- Live stats updated every 1 second: file size, segment indicator, packet rate

### 3.4 Capture History Row (Zone C)

```
┌──────────────────────────────────────────────────┐
│  capture-a1b2   Streaming / Video   ● completed  │
│  wlan0 · 58s · 24,531 pkts · 18.4 MB            │
│  Today 14:32                                     │
│                                                  │
│  ┌─ Quick Stats ─────────────────────────────┐   │
│  │ Retx: 1.4%  │ Throughput: 2.5 Mbps avg   │   │
│  │ DNS queries: 142  │ Top: manifest.prod... │   │
│  └───────────────────────────────────────────┘   │
│                                                  │
│  [View Details]  [AI Diagnosis]  [Download pcap] │
│                                          [Delete]│
└──────────────────────────────────────────────────┘
```

Quick Stats are pack-specific:
- **Connectivity:** "Reachable: yes · DNS: ok · Avg latency: 12ms"
- **DNS:** "Queries: 89 · NXDOMAIN: 0 · Slow: 1"
- **HTTPS:** "Retx: 0.8% · Connections: 14 · RSTs: 0"
- **Streaming:** "Retx: 1.4% · Throughput: 2.5 Mbps avg"
- **Security:** "Unique IPs: 23 · Unusual ports: 2 · Rogue DNS: 0"

### 3.5 Detail View

Clicking [View Details] opens an inline detail view (same pattern as SessionPanel list → detail):

- **Header:** capture ID, pack badge, status, interface, duration, BPF
- **Capture Statistics section** (auto-extracted, always available):
  - Protocol breakdown bars
  - TCP health table with status indicators (green/yellow/red per threshold)
  - Throughput timeline sparkline (inline SVG polyline from intervals array)
  - Top conversations table
  - DNS summary
- **AI Diagnosis section** (on-demand):
  - [Get AI Diagnosis] button if not yet analyzed
  - Full findings with evidence citations, confidence badges, recommendations
  - "How to read this" expandable disclaimer

### 3.6 AI Diagnosis Presentation

Each AI finding follows this template:

```
┌─ ⚠ HIGH ─ Retransmissions ──────────────────────┐
│                                                  │
│  TCP retransmission rate of 1.4% on the primary  │
│  media flow exceeds the 1% threshold for         │
│  reliable ABR streaming.                         │
│                                                  │
│  Evidence:                                       │
│  · 312 retransmissions / 22,100 TCP packets      │
│  · Concentrated at 22s and 38s marks             │
│  · Correlates with throughput dips <2 Mbps       │
│                                                  │
│  Affected flows:                                 │
│  192.168.4.10:54321 → 104.16.132.229:443         │
│                                                  │
│  Likely causes:                                  │
│  · WiFi channel contention                       │
│  · Upstream bandwidth saturation                 │
│                                                  │
│  Next steps:                                     │
│  · Run WiFi scan to check channel congestion     │
│  · Run connectivity pack during stall window     │
│                                                  │
│  Confidence: HIGH                                │
│  Based on: retransmission count + throughput      │
│  correlation + expert alerts                     │
└──────────────────────────────────────────────────┘
```

### 3.7 Warnings and Guardrails

| Trigger | Message | Placement |
|---------|---------|-----------|
| 2 captures running | "Maximum concurrent captures reached. Stop a running capture." | Toast + dimmed cards |
| Disk < 200 MB | "Low disk space. Clear old captures or connect USB storage." | Yellow banner above Zone A |
| Duration > 600s | "Long captures generate large files. Ring buffer recommended." | Inline under Duration |
| AI not configured | "AI analysis requires an API key. Configure in System → Settings." | Replaces AI Diagnosis button |
| Auto-retention pruned | "Auto-cleaned {n} old capture(s) to free {x} MB." | Toast notification |
| Legacy capture | "No summary available (pre-v2 capture). AI Diagnosis still works." | Inline in history row |

### 3.8 Status Badges

| Status | Label | Style |
|--------|-------|-------|
| RUNNING | recording | Green pulsing dot + green text |
| PROCESSING | processing | Blue badge with spinner |
| COMPLETED | completed | Green badge |
| STOPPED | stopped | Yellow badge |
| ERROR | error | Red badge |

### 3.9 Component Architecture

| UI Section | Component | Notes |
|---|---|---|
| Captures tab root | `CaptureManager.tsx` | Orchestrator — renders zones |
| Quick Capture cards | `QuickCapture.tsx` | Card grid + inline config expansion |
| Active capture progress | `ActiveCapture.tsx` | Live progress card |
| Capture history list | `CaptureHistory.tsx` | Enhanced rows with inline stats |
| Capture detail view | `CaptureDetail.tsx` | Stats dashboard + AI section |

---

## 4. Capture Modes and Presets (Analysis Packs)

### 4.1 Pack Definitions

Each pack defines: BPF filter, default duration, tshark stat queries, AI focus areas, and threshold rules.

#### Connectivity Check

| Property | Value |
|----------|-------|
| **Purpose** | "Is the network working? Can I reach the internet?" |
| **BPF** | `icmp or (tcp[tcpflags] & tcp-syn != 0) or udp port 53` |
| **Duration** | 30s |
| **Max size** | 50 MB |
| **Stat queries** | `io,phs`, `expert`, `endpoints,ip`, DNS extraction, ICMP extraction |
| **AI focus** | Packet loss, unreachable hosts, DNS failures, gateway health |
| **When to use** | "Nothing works" — first-pass triage |

#### DNS Troubleshoot

| Property | Value |
|----------|-------|
| **Purpose** | "Are DNS lookups working correctly and quickly?" |
| **BPF** | `udp port 53 or tcp port 53` |
| **Duration** | 60s |
| **Max size** | 20 MB |
| **Stat queries** | `io,phs`, `io,stat,1`, DNS field extraction |
| **AI focus** | Slow lookups (>200ms), NXDOMAIN, SERVFAIL, unusual query patterns, DNS hijacking |
| **When to use** | Apps slow to load, intermittent connectivity |

#### HTTPS / Web

| Property | Value |
|----------|-------|
| **Purpose** | "Are web requests completing quickly and correctly?" |
| **BPF** | `tcp port 80 or tcp port 443 or tcp port 8080` |
| **Duration** | 60s |
| **Max size** | 100 MB |
| **Stat queries** | `io,phs`, `conv,tcp`, `io,stat,1`, `expert`, TLS ClientHello extraction |
| **AI focus** | Slow connections, retransmission rate, RST storms, TLS version issues |
| **When to use** | Web browsing slow, API calls failing |

#### Streaming / Video

| Property | Value |
|----------|-------|
| **Purpose** | "Why is the video buffering, freezing, or low quality?" |
| **BPF** | `tcp port 80 or tcp port 443 or udp portrange 1024-65535` |
| **Duration** | 120s |
| **Max size** | 100 MB |
| **Stat queries** | `io,phs`, `conv,tcp`, `io,stat,1`, `expert`, DNS extraction |
| **AI focus** | Throughput dips below ABR thresholds (2/5/10/15 Mbps), retransmission bursts, CDN patterns, UDP loss |
| **When to use** | Buffering, pixelation, quality drops |

#### Security / Anomaly

| Property | Value |
|----------|-------|
| **Purpose** | "Is there unexpected traffic, rogue DNS, or suspicious patterns?" |
| **BPF** | (none — capture all traffic) |
| **Duration** | 60s |
| **Max size** | 100 MB |
| **Stat queries** | `io,phs`, `conv,tcp`, `conv,udp`, `endpoints,ip`, DNS extraction, TLS ClientHello |
| **AI focus** | Unexpected outbound connections, DNS exfiltration, port scanning, ARP spoofing, non-RFC1918 sources |
| **When to use** | Security audit, unexpected bandwidth usage |

#### Custom (Advanced)

Retains the existing form: manual interface, BPF, duration, packet limits. Defaults to a general stat query set. Ring buffer off by default (configurable).

### 4.2 tshark Stat Queries by Pack

| Query | Connectivity | DNS | HTTPS | Streaming | Security |
|-------|:-:|:-:|:-:|:-:|:-:|
| `-z io,phs` (protocol hierarchy) | x | x | x | x | x |
| `-z conv,tcp` (TCP conversations) | | | x | x | x |
| `-z conv,udp` (UDP conversations) | | x | | x | x |
| `-z io,stat,1` (throughput/sec) | | x | x | x | |
| `-z expert` (retx, errors) | x | | x | x | |
| `-z endpoints,ip` (unique IPs) | x | | | | x |
| DNS field extraction | x | x | | x | x |
| ICMP field extraction | x | | | | |
| TLS ClientHello extraction | | | x | | x |

---

# Part II — Backend Architecture

## 5. System Architecture

### 5.1 Component Map

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND                                 │
│  CaptureManager.tsx (orchestrator)                              │
│  ├── QuickCapture.tsx        — pack card grid + inline config   │
│  ├── ActiveCapture.tsx       — live progress card(s)            │
│  ├── CaptureHistory.tsx      — completed capture list           │
│  └── CaptureDetail.tsx       — stats dashboard + AI diagnosis   │
├─────────────────────────────────────────────────────────────────┤
│                      API LAYER                                  │
│  routers/captures.py         — HTTP endpoints (existing + new)  │
├─────────────────────────────────────────────────────────────────┤
│                    SERVICE LAYER                                │
│  services/capture.py         — capture engine (dumpcap mgmt)    │
│  services/capture_stats.py   — NEW: stat extraction + parsing   │
│  services/capture_retention.py — NEW: pruning + disk mgmt       │
│  services/ai_analyzer.py     — AI pipeline (modified)           │
│  services/session_manager.py — session/artifact linkage         │
├─────────────────────────────────────────────────────────────────┤
│                    MODEL LAYER                                  │
│  models/capture.py           — data models (extended)           │
│  models/analysis_packs.py    — NEW: pack configs + BPF + queries│
├─────────────────────────────────────────────────────────────────┤
│                    INFRASTRUCTURE                               │
│  utils/shell.py              — subprocess execution (unchanged) │
│  services/storage.py         — path resolution (unchanged)      │
│  config.py                   — settings (add capture defaults)  │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 Responsibilities

| Component | Owns | Does NOT own |
|-----------|------|-------------|
| `capture.py` | Process lifecycle (start/stop/monitor), ring buffer, segment merge | Stat extraction, AI, retention |
| `capture_stats.py` | tshark queries, output parsing, summary JSON | Process mgmt, AI calls |
| `capture_retention.py` | Disk tracking, age/count/size pruning | Capture lifecycle |
| `ai_analyzer.py` | Prompt construction, provider calls, response validation | Stat extraction |
| `analysis_packs.py` | Pack definitions (BPF, duration, queries, thresholds) | Everything else — pure config |
| `captures.py` (router) | HTTP handling, request validation | Business logic |

### 5.3 File Layout After Post-Processing

```
/var/lib/wifry/captures/
├── {id}.json               # capture metadata
├── {id}.pcap               # merged pcap (or single file)
├── {id}.summary.json       # structured stats + interest annotations (NEW)
├── {id}.analysis.json      # AI analysis (on-demand)
└── {id}_segments/          # ring buffer segments (deleted after merge)
```

### 5.4 API Changes (Additive Only)

| Change | Breaking? |
|--------|-----------|
| `StartCaptureRequest.analysis_pack` (optional, default "custom") | No |
| `StartCaptureRequest.ring_buffer` (optional) | No |
| `StartCaptureRequest.segment_size_mb` (optional) | No |
| `CaptureInfo.analysis_pack` | No (null for old captures) |
| `CaptureInfo.segment_count` | No (0 for old) |
| `CaptureInfo.summary_available` | No (false for old) |
| `GET /captures/{id}/summary` new endpoint | New, no break |
| `GET /captures/packs` new endpoint | New, no break |
| `GET /captures/status` new endpoint (system health) | New, no break |

---

## 6. dumpcap vs tshark

### Decision: dumpcap captures. tshark analyzes. No exceptions.

| Criterion | dumpcap | tshark |
|-----------|---------|--------|
| **Purpose** | Capture packets to disk | Decode + analyze completed files |
| **RAM** | ~5 MB RSS | 30-80 MB (dissectors loaded) |
| **CPU during capture** | ~2-5% of one core | ~15-30% of one core |
| **Ring buffer** | Native: `-b filesize:10240 -b files:10` | Works but wastes RAM |
| **BPF filter** | Yes (`-f`) | Yes |

```
Capture:     dumpcap -i wlan0 -F pcap -b filesize:10240 -b files:10 -f "tcp" -w /captures/{id}.pcap
Stop:        mergecap -w /captures/{id}.pcap /captures/{id}_*.pcap
Analyze:     tshark -r /captures/{id}.pcap -q -z io,phs
             tshark -r /captures/{id}.pcap -q -z conv,tcp
             tshark -r /captures/{id}.pcap -q -z expert
```

**Why not tshark for capture?** On RPi 5, `tshark -w` loads all dissectors into memory even when just writing raw packets. That wastes 30-80 MB per process. With 2 concurrent captures, that is 160 MB of unnecessary overhead. dumpcap is the same engine Wireshark uses internally — purpose-built for raw capture.

**Migration:** Replace `tshark -i ... -w` with `dumpcap -i ... -w` in capture.py. All post-processing tshark commands remain unchanged. Both tools ship with the `tshark` apt package.

---

## 7. Rolling Capture / Retention Design

### 7.1 Ring Buffer Capture

**Default for all packs.** Segments of 10 MB, max 10 files = 100 MB ceiling.

```bash
dumpcap -i wlan0 -F pcap \
  -b filesize:10240 \     # 10 MB per segment
  -b files:10 \           # max 10 segments
  -a duration:120 \       # auto-stop after 120s
  -f "tcp port 443" \
  -w /var/lib/wifry/captures/{id}_segments/{id}.pcap
```

dumpcap names segments automatically: `{id}_00001_{timestamp}.pcap`, etc. When segment 11 would be created, segment 1 is deleted. On capture stop, segments are merged via mergecap.

**Segment sizing rationale:**

| Size | Segments at 100 MB | Flush freq (20 Mbps) | Verdict |
|---|---|---|---|
| 1 MB | 100 | Every ~0.5s | Too many files |
| 5 MB | 20 | Every ~2.5s | Acceptable |
| **10 MB** | **10** | **Every ~5s** | **Best balance: matches SD erase block, manageable count** |
| 25 MB | 4 | Every ~12s | Too coarse |

### 7.2 Merge on Stop

```bash
mergecap -w /var/lib/wifry/captures/{id}.pcap /var/lib/wifry/captures/{id}_segments/{id}_*.pcap
rm -rf /var/lib/wifry/captures/{id}_segments/
```

mergecap is streaming (~10 MB RSS). ~2 seconds for 100 MB. If merge would produce >200 MB, keep segments and process stats per-segment.

### 7.3 Retention Policy

**Auto-enforced after every capture completion:**

| Rule | Threshold | Action |
|------|-----------|--------|
| Max capture count | 20 | Delete oldest completed |
| Max total storage | 500 MB | Delete oldest completed |
| Max capture age | 7 days | Delete on next capture |
| Running captures | Exempt | Never auto-deleted |
| Session-linked captures | Exempt while session active | Pruned when session discarded |

**Enforcement order:** age-based first, then count-based, then size-based. Skip captures linked to active sessions.

**Daily maintenance task:** Also runs retention, plus cleans orphaned segments, summary files, and analysis files that lost their parent capture.

### 7.4 Disk Budget (RPi 5, 32 GB SD)

```
System + OS:              ~4 GB
WiFry application:        ~200 MB
Captures (capped):        500 MB
Sessions + artifacts:     ~200 MB
Logs + runtime state:     ~100 MB
─────────────────────────
Total WiFry footprint:    ~1 GB (3% of 32 GB)
Headroom:                 ~27 GB
```

---

# Part III — AI Analysis Framework

## 8. Derived Artifact Pipeline

### 8.1 Three-Stage Pipeline

```
Raw pcap on disk
       │
       ▼
┌──────────────────────────────────────────────────┐
│  Stage 1: Deterministic Extraction (tshark)      │
│  Cost: $0   Latency: 5-15s   Runs: always       │
│  Output: CaptureSummary JSON (~3-8 KB)           │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│  Stage 2: Interest Detection (threshold rules)   │
│  Cost: $0   Latency: <100ms  Runs: always        │
│  Output: InterestAnnotations (flags, windows)    │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼  (user clicks "Get AI Diagnosis")
┌──────────────────────────────────────────────────┐
│  Stage 3: AI Interpretation (on-demand)          │
│  Cost: $0.01-0.03  Latency: 3-10s               │
│  Output: AnalysisResultV2 JSON                   │
└──────────────────────────────────────────────────┘
```

Stages 1-2 power the stats dashboard for free. Stage 3 is optional. A user who never configures an AI key still gets a useful capture tool with health badges, threshold alerts, and structured statistics.

### 8.2 CaptureSummary Schema

Every completed capture produces one `CaptureSummary` JSON. Sections present depend on which tshark queries the pack defines.

```python
class CaptureSummary(BaseModel):
    meta: CaptureMeta                        # id, pack, interface, BPF, timing, counts
    protocols: list[ProtocolBreakdown]       # nested protocol tree with pkt/byte/pct
    tcp_health: TcpHealth | None             # retx rate, dup acks, zero windows, RSTs, SYN/FIN counts
    conversations: list[Conversation]        # top 20 by bytes, with per-flow retx
    dns: DnsSummary | None                   # queries, response times, NXDOMAIN, resolvers
    throughput: ThroughputSummary | None      # avg/peak/min/stddev + 1-sec intervals
    expert_alerts: ExpertSummary | None      # error/warning/note counts + top alerts
    icmp: IcmpSummary | None                 # echo/reply/unreachable/TTL, per-target RTT
    endpoints: list[EndpointEntry] | None    # top 30 IPs by bytes, RFC1918 tagged
    tls_handshakes: list[TlsHandshake] | None  # SNI, TLS version, connection count
    interest: InterestAnnotations | None     # anomaly flags, interesting windows, focus flows
```

**Size budget:** Typically 3-8 KB. Max 20 KB. Sections with >N entries are truncated with a `"truncated": true, "total_count": M` annotation.

### 8.3 Interest Detection

Before AI sees anything, deterministic rules flag noteworthy findings:

```python
class InterestAnnotations(BaseModel):
    anomaly_flags: list[AnomalyFlag]         # threshold violations with field/value/severity
    interesting_windows: list[InterestWindow] # time windows with throughput drops, retx bursts
    focus_flows: list[FocusFlow]             # conversations AI should examine closely
    overall_health: str                      # "healthy" | "degraded" | "unhealthy"
    pack_specific_notes: list[str]
```

**Health classification:** If any flag is critical → "unhealthy". If any flag is warning → "degraded". Otherwise → "healthy". This drives the green/yellow/red badge in the UI before any AI call.

**Pack-specific thresholds (examples):**

| Pack | Field | Warning | Critical |
|------|-------|---------|----------|
| Connectivity | `icmp.loss_rate_pct` | >5% | >20% |
| DNS | `dns.p95_response_time_ms` | >300ms | >1000ms |
| HTTPS | `tcp_health.retransmission_rate_pct` | >1% | >5% |
| Streaming | `tcp_health.retransmission_rate_pct` | >0.5% | >2% |
| Streaming | `throughput.min_bps` | <2 Mbps | <500 Kbps |
| Security | Non-RFC1918 src on LAN | — | any |

**Interesting window detection:** Analyze throughput intervals to find drops >60% below average sustained for 3+ seconds. These are flagged for the AI to examine.

---

## 9. AI Analysis Framework

### 9.1 Design Philosophy

Three rules:

1. **AI interprets; it never observes.** It sees CaptureSummary JSON, never raw packets.
2. **Every claim cites its source.** Each finding references a specific field and value from the input.
3. **Confidence is earned, not declared.** HIGH/MEDIUM/LOW based on explicit rules. No percentages.

### 9.2 AI Input Schema

The AI receives a single JSON document:

```json
{
  "analysis_pack": "streaming",
  "pack_description": "Traffic captured to diagnose video streaming quality issues.",
  "capture_context": { "interface", "bpf_filter", "duration_secs", "total_packets", "total_bytes" },
  "pre_identified_issues": [ { "field", "value", "threshold", "severity", "label" } ],
  "focus_flows": [ { "src", "dst", "reason" } ],
  "overall_health": "degraded",
  "summary_data": { /* full CaptureSummary minus meta */ },
  "truncations": [ { "section", "shown", "total" } ]
}
```

**Narrowing strategy:** Throughput intervals are trimmed to only interesting windows + 5s context on each side. Conversations trimmed to top 10 + flagged focus flows. DNS trimmed to top 10 queried + all slow + all failing. Aggregate stats (avg, peak, min) always reflect the complete capture.

### 9.3 AI Output Schema (AnalysisResultV2)

```python
class Finding(BaseModel):
    id: str                          # "F1", "F2" — stable reference
    title: str                       # one-line summary
    severity: str                    # critical, high, medium, low, info
    confidence: Confidence           # HIGH, MEDIUM, LOW
    category: str                    # retransmissions, throughput, dns, tls, security, protocol
    description: str                 # 2-4 sentences
    evidence: list[EvidenceCitation] # MUST have at least one
    affected_flows: list[str]
    likely_causes: list[str]
    next_steps: list[str]
    cross_references: list[str]      # ["F2"] — related findings

class InsufficientEvidenceNote(BaseModel):
    area: str                        # what couldn't be analyzed
    reason: str                      # why
    what_would_help: str             # what capture/data would answer this

class AnalysisResultV2(BaseModel):
    capture_id: str
    analysis_pack: str
    executive_summary: str           # 2-4 sentences, non-technical
    health_verdict: str              # healthy, degraded, unhealthy
    findings: list[Finding]          # ordered by severity descending
    insufficient_evidence: list[InsufficientEvidenceNote]
    comparative_notes: str | None    # only for two-capture comparison
    metadata: AnalysisMetadata       # provider, model, tokens, timing
```

### 9.4 Guardrails

**Input guardrails (before AI call):**
- Summary size cap: reject if >20 KB
- Empty capture: don't call if <10 packets
- Rate limit: 1 call per 30 seconds per capture
- API key check: return helpful error if unconfigured

**Output guardrails (after AI response):**
- Drop findings with no evidence citations
- Drop citations referencing fields not in the input
- Correct cited values that don't match actual data
- LOW confidence findings cannot be "critical" severity
- Max 10 findings per analysis
- Validate JSON against Pydantic model; fallback to raw summary on failure

**Prompt injection defense:** Input is entirely machine-generated from tshark. DNS domain names are sanitized (strip non-printable, reject prompt-injection patterns, enforce RFC 1035 length).

### 9.5 Confidence Decision Tree

```
Does the finding cite >=2 corroborating evidence fields?
├── YES: Do cited values clearly exceed thresholds?
│   ├── YES → HIGH
│   └── NO (borderline) → MEDIUM
└── NO (single field):
    ├── Strongly exceeds threshold (>2x)? → MEDIUM
    ├── Does not strongly exceed? → LOW
    └── Field is null/missing? → InsufficientEvidenceNote (not a finding)
```

### 9.6 "Insufficient Evidence" Rules

The AI must produce an InsufficientEvidenceNote when:
- A field it would normally analyze is null or missing
- A section is truncated and its conclusion depends on the full dataset
- Capture duration <15s and it's asked about patterns
- Total packet count for relevant protocol <100
- It wants to claim something outside the capture's BPF scope

### 9.7 Comparative Analysis (Phase 2)

Two-capture comparison uses pre-computed deltas plus both summaries in a single AI call:

```python
class ComparisonDeltas(BaseModel):
    retransmission_rate_delta: float | None
    avg_bps_delta: float | None
    avg_dns_time_delta_ms: float | None
    degraded_metrics: list[str]
    improved_metrics: list[str]
    unchanged_metrics: list[str]
```

Delta rules: retransmission rate higher = worse. Throughput lower = worse. DNS time higher = worse. Thresholds for significance: retx delta >0.5%, throughput change >10%, DNS time change >50ms.

### 9.8 Cost Control

| Control | Value |
|---|---|
| Max input tokens | ~5,000 (20 KB / ~4 chars per token) |
| Max output tokens | 4,096 |
| Rate limit | 1 call / 30s / capture |
| Model | Claude Sonnet / GPT-4o-mini (not Opus/4o) |
| Caching | Saved to disk; re-analyze requires explicit action |
| Estimated cost | $0.01-0.03 per analysis |

---

## 10. Session Model and Anomaly Linking

### 10.1 Current State

Sessions exist (`TestSession`) with thin artifact linkage. No timeline, no correlation with impairment changes.

### 10.2 Proposed Timeline Model

```python
class TimelineEvent(BaseModel):
    timestamp: str                   # ISO 8601
    event_type: str                  # capture_started, capture_completed, impairment_applied, etc.
    data: dict                       # event-specific payload

class TestSession(BaseModel):
    # ... existing fields ...
    timeline: list[TimelineEvent]    # NEW
```

Each service appends events:
- `capture.py` → `capture_started`, `capture_completed` (with pack, summary snippet)
- `session_manager.py` → `session_started`, `session_completed`
- `impairments.py` → `impairment_applied`, `impairment_cleared` (with profile name)
- Future: anomaly detector → `anomaly_detected` (with type, capture_id)

### 10.3 Anomaly-Triggered Preserve (Phase 3)

When background capture is active and an anomaly is detected (retransmission spike, DNS failure cluster, throughput cliff), automatically snapshot the ring buffer into a named capture:

```python
async def on_anomaly_detected(anomaly_type: str, timestamp: float):
    if background_capture_active():
        capture_id = await snapshot_ring_buffer(
            preserve_seconds=60,
            name=f"anomaly-{anomaly_type}-{timestamp}",
        )
        if active_session:
            session_manager.record_event("anomaly_detected", {
                "type": anomaly_type,
                "capture_id": capture_id,
            })
```

---

# Part IV — RPi 5 Optimization

## 11. Resource Guardrails

### 11.1 Hardware Budget

| Resource | RPi 5 total | Capture budget | Why |
|---|---|---|---|
| CPU | 4× Cortex-A76 @ 2.4 GHz | ~1 core sustained | Other 3 run AP, NAT, FastAPI, DNS |
| RAM | 8 GB LPDDR4X | 200 MB total | OS ~500 MB, Python ~150 MB, AP stack ~100 MB |
| Disk write (SD) | ~25 MB/s | ~10 MB/s sustained | Leave headroom for journal/logs |
| Storage | 32-128 GB | 500 MB captures | SD cards are small |

### 11.2 Resource Budget per Capture Phase

| Phase | CPU | RAM | Disk I/O | Duration |
|---|---|---|---|---|
| Capture (dumpcap) | ~5% 1 core | ~5 MB | Sequential write, 1-10 MB/s | User-defined |
| Merge (mergecap) | ~20% 1 core | ~10 MB | Read segments + write merged | ~2s per 100 MB |
| Stats (tshark ×5-8) | ~80% 1 core | 50-80 MB | Read merged pcap ×N | 5-15s per 100 MB |
| AI call | ~0% | ~1 MB | Network only | 3-10s |
| **Total post-processing** | — | **~80 MB peak** | — | **10-30s typical** |

### 11.3 Pre-Capture Checks

```python
async def preflight_check() -> list[str]:
    reasons = []
    running = count_running_captures()
    if running >= 2:
        reasons.append("Maximum 2 concurrent captures reached")
    free_mb = shutil.disk_usage(CAPTURES_DIR).free / (1024 * 1024)
    if free_mb < 200:
        reasons.append(f"Insufficient disk space: {free_mb:.0f} MB free, need 200 MB")
    mem = psutil.virtual_memory()
    if mem.available < 256 * 1024 * 1024:
        reasons.append(f"Insufficient RAM: {mem.available // (1024*1024)} MB available")
    return reasons
```

### 11.4 Mid-Capture Monitoring

Check free disk space every 10 seconds during capture. Emergency stop if <50 MB free.

### 11.5 Post-Processing Controls

| Control | Value | Why |
|---|---|---|
| `nice -n 10` | Lower CPU priority | Don't starve AP, NAT, FastAPI |
| `ionice -c2 -n 7` | Best-effort low-priority I/O | Don't block journal writes |
| Per-query timeout | 60 seconds | Single query on 100 MB ~10s; 60s generous |
| Total pipeline timeout | 5 minutes | Full pack ~90s; 5 min safety |
| Post-process lock | 1 concurrent | Prevent disk thrashing |
| Page cache pre-warm | `cat {pcap} > /dev/null` before queries | Sequential read faster than tshark's access |

### 11.6 Progressive Rendering

Save partial summary after each tshark query completes. Frontend polls `/captures/{id}/summary` and renders whatever's available. User sees protocol breakdown within 5 seconds of capture completion, not 30.

**Query ordering by value:**
1. `io,phs` (protocol overview) — ~2s
2. `expert` (health badge) — ~3s
3. `io,stat,1` (throughput chart) — ~2s
4. `conv,tcp` (conversations) — ~3s
5. DNS extraction — ~2s
6. Remaining queries...

### 11.7 systemd Resource Limits

Add to `wifry-backend.service`:

```ini
[Service]
MemoryMax=2G
MemoryHigh=1.5G
CPUWeight=80
LimitNOFILE=4096
OOMScoreAdjust=200
```

This lets the kernel kill WiFry before hostapd, dnsmasq, or sshd.

### 11.8 Anti-Patterns

| Anti-Pattern | Why it's bad | Do instead |
|---|---|---|
| tshark for capture | 30-80 MB RSS per process | dumpcap (5 MB) |
| Post-process during capture | Packet drops | Wait for capture to finish |
| Parallel tshark queries | 5 × 100 MB = disk thrash | Sequential + page cache |
| Python pcap parsing (scapy) | 1 GB+ RAM for 100 MB pcap | tshark subprocess |
| Compress during capture | CPU contention, drops | Compress after post-processing |
| No retention | SD card fills in weeks | 20 captures / 500 MB / 7 days |

---

# Part V — Delivery

## 12. Phased Roadmap

### Phase 1: MVP (v0.2.x — 1 sprint)

| Feature | Effort | Priority |
|---|---|---|
| Analysis packs model + config | M | P0 |
| dumpcap switch + ring buffer | M | P0 |
| Structured stat extraction (capture_stats.py) | M | P0 |
| Interest detection (threshold rules) | S | P0 |
| Concurrent capture semaphore (max 2) | S | P0 |
| Auto-retention (20/500MB/7d) | S | P0 |
| Quick Capture card UI | M | P0 |
| Active capture progress UX | S | P0 |
| Stats dashboard (renders summary.json) | M | P0 |
| AI prompt migration to pack-specific templates | M | P1 |
| AnalysisResultV2 with evidence citations | M | P1 |

**Week-by-week:**

```
Week 1:  analysis_packs.py model + PACK_CONFIGS dict
         Extended CaptureInfo/StartCaptureRequest models
         dumpcap switch + ring buffer in capture.py
         Segment merge via mergecap

Week 2:  capture_stats.py — 8 tshark output parsers
         CaptureSummary model + JSON generation
         InterestAnnotations + threshold rules per pack
         Concurrent semaphore + retention enforcement

Week 3:  QuickCapture.tsx — card grid + inline config
         ActiveCapture.tsx — progress card with live stats
         CaptureHistory.tsx — rows with inline pack stats
         CaptureDetail.tsx — stats dashboard (protocol bars, TCP health, throughput sparkline)

Week 4:  Pack-specific AI prompt templates
         AnalysisResultV2 model + output guardrails
         AI input builder with narrowing
         Integration testing on RPi 5
```

### Phase 2: Next (v0.3.x)

| Feature | Description |
|---|---|
| Background capture | Always-on ring buffer when AP active |
| Snapshot preserve | "Preserve last 60s" copies ring buffer to named capture |
| Comparative analysis | Two-capture diff with pre-computed deltas + AI |
| Capture templates | Save custom filter+duration+pack combos |
| Stats-only mode | Extract stats without keeping pcap (saves disk) |
| Session timeline | TimelineEvent model + timeline view in SessionPanel |

### Phase 3: Roadmap (v0.4+)

| Feature | Description |
|---|---|
| Anomaly-triggered preserve | Auto-snapshot on retx spike, DNS failure, throughput cliff |
| Streaming QoE correlation | Cross-reference with HLS/DASH segment timing |
| Distributed capture | AP interface + upstream simultaneously |
| pcapng migration | Per-packet comments, multi-interface metadata |
| Export to CloudShark | Upload filtered pcap slices for team collaboration |

---

## 13. Acceptance Criteria

### AC-1: Analysis Packs

```
GIVEN the user opens the Captures tab
WHEN they see the Quick Capture section
THEN they see 5 cards: Connectivity, DNS, HTTPS/Web, Streaming/Video, Security
AND clicking a card expands inline config with pack-specific defaults
AND the user can adjust duration and interface before starting
```

### AC-2: dumpcap Ring Buffer

```
GIVEN a capture is started with ring_buffer enabled
THEN the system uses dumpcap with -b filesize:10240 -b files:10
AND on stop/complete, segments merge into a single pcap via mergecap
AND segments are deleted after successful merge
AND CaptureInfo shows segment_count
```

### AC-3: Structured Summary Extraction

```
GIVEN a capture has completed
WHEN post-processing runs
THEN pack-specific tshark stats are extracted
AND a typed CaptureSummary JSON is saved as {id}.summary.json
AND the summary is <=20 KB
AND the summary powers the stats dashboard without AI
```

### AC-4: Interest Detection

```
GIVEN a CaptureSummary exists
WHEN interest detection runs
THEN threshold violations are flagged as AnomalyFlags
AND throughput drops are identified as InterestWindows
AND an overall_health classification is computed (healthy/degraded/unhealthy)
AND the health badge appears in the UI
```

### AC-5: Concurrent Capture Limit

```
GIVEN 2 captures are running
WHEN the user tries to start a third
THEN the API returns 429 with "Maximum concurrent captures reached"
AND Quick Capture cards show dimmed state with tooltip
```

### AC-6: Auto-Retention

```
GIVEN the retention limits are 20 captures / 500 MB / 7 days
WHEN a new capture completes
THEN captures over limits are pruned (oldest first, skip active-session-linked)
AND a toast notification shows "Auto-cleaned N captures to free X MB"
```

### AC-7: AI Uses Summary JSON

```
GIVEN a capture has a .summary.json
WHEN the user clicks "Get AI Diagnosis"
THEN the AI receives the structured summary + interest annotations
AND the pack-specific prompt template is used
AND the response includes evidence citations and confidence levels
AND total AI input is <20 KB
```

### AC-8: Capture Progress UX

```
GIVEN a capture is running
THEN the Active zone shows: elapsed/total progress bar, file size, segment indicator, packet rate
AND stats update every 1 second
AND a [Stop] button is available
```

---

## 14. Risks and Tradeoffs

### Decision Log

| # | Decision | Risk | Mitigation | Tradeoff |
|---|---|---|---|---|
| D1 | dumpcap for capture, tshark for analysis | Two tools to manage | Both ship with `tshark` package | Slightly complex subprocess mgmt for 60% less RAM |
| D2 | Ring buffer as default | Oldest packets overwritten | Most recent packets most relevant; Custom mode can disable | Lose old packets for bounded disk |
| D3 | Max 2 concurrent captures | Power users want more | Practical limit for RPi 5 RAM/CPU | Stability over flexibility |
| D4 | Structured summary as AI input | May miss edge cases | Summary is superset of current truncated dumps; raw pcap always available | Less AI flexibility for deterministic, cheap input |
| D5 | Auto-retention 20/500MB/7d | User loses old captures | Session-linked exempt; notification on prune; bundled export | Disk health over unlimited history |
| D6 | pcap (not pcapng) in MVP | No per-packet comments | pcapng migration in phase 3; pcap universally compatible | Compatibility now, richer format later |
| D7 | Post-process only (no live decode) | No real-time stats during capture | Live file size/packet rate estimation is cheap | RPi 5 can't afford live decode without drops |
| D8 | No compression during capture | Uncompressed files use more disk | Ring buffer caps total size; compress post-analysis if needed | Packet integrity over disk savings |

### Risks

| Risk | Severity | Mitigation |
|---|---|---|
| SD card write wear from captures | Medium | Short default durations (30-120s); USB 3 recommended for background capture |
| mergecap failure on large ring buffer | Low | mergecap is streaming (~10 MB RSS); tested to 500 MB |
| tshark OOM on large pcap | Medium | Cap at 100 MB; `ulimit -v 512M` on subprocess; kill if VmRSS >400 MB |
| Thermal throttling during sustained post-processing | Medium | `nice -n 10`; 5s cooldown between pipeline runs; require heatsink |
| Zombie processes after backend crash | Medium | Reconcile on startup: mark RUNNING as STOPPED, trigger post-processing on recovered pcaps |

---

## 15. Implementation Plan

### 15.1 New Files

| File | Purpose |
|---|---|
| `backend/app/models/analysis_packs.py` | `AnalysisPack` enum + `PACK_CONFIGS` dict |
| `backend/app/services/capture_stats.py` | tshark query execution + 8 output parsers |
| `backend/app/services/capture_retention.py` | Count/size/age-based pruning |
| `frontend/src/components/captures/QuickCapture.tsx` | Pack card grid + inline config |
| `frontend/src/components/captures/ActiveCapture.tsx` | Live progress card |
| `frontend/src/components/captures/CaptureHistory.tsx` | Enhanced history rows |
| `frontend/src/components/captures/CaptureDetail.tsx` | Stats dashboard + AI section |

### 15.2 Modified Files

| File | Changes |
|---|---|
| `backend/app/models/capture.py` | Add `PROCESSING` status, `AnalysisResultV2`, `CaptureSummary`, extended `CaptureInfo` and `StartCaptureRequest` |
| `backend/app/services/capture.py` | dumpcap switch, ring buffer, segment merge, semaphore, post-processing orchestration |
| `backend/app/services/ai_analyzer.py` | Load summary.json instead of raw extraction; pack-specific prompts; output validation |
| `backend/app/routers/captures.py` | New endpoints: `/packs`, `/{id}/summary`, `/status` |
| `backend/app/config.py` | `CAPTURE_DEFAULTS` dict |
| `frontend/src/components/CaptureManager.tsx` | Refactor to orchestrator rendering sub-components |

### 15.3 Key Pseudocode

**start_capture with pack resolution:**

```python
async def start_capture(req: StartCaptureRequest) -> CaptureInfo:
    # 1. Preflight: concurrent limit, disk space, RAM
    errors = await preflight_check()
    if errors:
        raise HTTPException(429 if "concurrent" in errors[0] else 507, errors[0])

    # 2. Resolve pack config
    pack = PACK_CONFIGS[req.analysis_pack]
    duration = req.max_duration_secs or pack.default_duration_secs
    bpf = pack.bpf if req.analysis_pack != "custom" else req.filters.to_bpf()
    use_ring = req.ring_buffer if req.ring_buffer is not None else pack.ring_buffer

    # 3. Build dumpcap command
    cmd = ["dumpcap", "-i", req.interface, "-F", "pcap"]
    if use_ring:
        cmd += ["-b", f"filesize:{pack.ring_buffer_segment_mb * 1024}",
                "-b", f"files:{pack.ring_buffer_max_segments}"]
    cmd += ["-a", f"duration:{duration}"]
    if bpf:
        cmd += ["-f", bpf]
    cmd += ["-w", str(pcap_path)]

    # 4. Launch subprocess, register monitor task
    async with _capture_semaphore:
        proc = await asyncio.create_subprocess_exec(*cmd, ...)
        _processes[capture_id] = proc
        asyncio.create_task(_monitor_capture(capture_id))
```

**_finalize_capture with merge + stats + retention:**

```python
async def _finalize_capture(capture_id: str):
    info = _captures[capture_id]
    info.status = CaptureStatus.PROCESSING

    # 1. Merge ring buffer segments
    if info.ring_buffer_enabled:
        segments = sorted(segments_dir.glob("*.pcap"))
        await run("mergecap", "-w", str(merged_path), *[str(s) for s in segments])
        shutil.rmtree(segments_dir)

    # 2. Fix permissions
    await run("chmod", "644", str(pcap_path), sudo=True)
    await run("chown", "wifry:wifry", str(pcap_path), sudo=True)

    # 3. Extract stats (serialized, nice'd)
    async with _post_process_lock:
        await run(f"cat {pcap_path} > /dev/null")  # pre-warm page cache
        summary = await capture_stats.extract_and_save(capture_id, info.analysis_pack)
        info.summary_available = summary is not None

    # 4. Update status
    info.status = CaptureStatus.COMPLETED
    save_metadata(info)

    # 5. Enforce retention
    await capture_retention.enforce()
```

### 15.4 Config Defaults

```python
CAPTURE_DEFAULTS = {
    "max_concurrent": 2,
    "retention_max_count": 20,
    "retention_max_bytes": 500 * 1024 * 1024,
    "retention_max_age_days": 7,
    "ring_buffer_segment_mb": 10,
    "ring_buffer_max_segments": 10,
    "post_processing_timeout_secs": 300,
    "ai_rate_limit_secs": 30,
    "disk_space_min_mb": 200,
    "emergency_disk_space_mb": 50,
}
```

---

## 16. AI Prompt Template Library

### 16.1 Shared System Prompt (all packs)

```
You are a network diagnostician embedded in WiFry, a WiFi test appliance running on Raspberry Pi.
You receive structured statistics extracted from a packet capture — never raw pcap data.

RULES — absolute constraints:

1. EVIDENCE REQUIRED: Every finding MUST cite at least one field from summary_data
   with its exact value. Do not round, estimate, or fabricate numbers.

2. CONFIDENCE LEVELS:
   - HIGH: Multiple corroborating data points clearly confirm the issue.
   - MEDIUM: One strong indicator or multiple weak indicators suggest the issue.
   - LOW: Pattern is suggestive but data insufficient for certainty.

3. INSUFFICIENT EVIDENCE: If capture data cannot answer a question, say so in the
   insufficient_evidence array. Do NOT speculate to fill gaps.

4. CAUSATION vs CORRELATION: Use "likely caused by" or "consistent with" — never
   "caused by" unless evidence is unambiguous.

5. SCOPE: Only analyze what the capture data shows. Do not speculate about server-side
   issues, application-layer behavior above protocol dissection, or WiFi PHY-layer details.
   The capture sees traffic at the WiFi AP interface.

6. TRUNCATION: If input includes "truncations", acknowledge partial data. Do not claim
   "only N conversations exist" when data was truncated.

7. FORMAT: Respond with valid JSON matching the AnalysisResultV2 schema.
   No markdown wrapping. No commentary outside JSON.

You MUST add an InsufficientEvidenceNote when:
- A field you would analyze is null or missing
- A section has "truncated": true and your conclusion depends on full data
- Capture duration <15 seconds and you're assessing stability
- Total packet count for relevant protocol <100
- You want to claim something outside the BPF scope

You MUST NOT:
- Present LOW confidence findings as established fact
- Fill gaps with assumptions about "typical" network behavior
- Claim a problem doesn't exist just because evidence is absent
  (say "not observed" not "not present")
```

### 16.2 Connectivity Pack Prompt

```
## Analysis Pack: Connectivity Check

This capture determines basic network health: can traffic reach the internet,
is DNS working, are there fundamental delivery problems?

PAY ATTENTION TO:
- ICMP echo/reply: Calculate packet loss. Any loss to the gateway is significant.
- DNS resolution: Are queries completing? Response times? NXDOMAIN or SERVFAIL?
- TCP connection setup: SYN packets getting SYN-ACK? High RST count?
- Retransmissions: Rate above 2% is concerning for basic connectivity.
- Unreachable messages: ICMP unreachable = routing or firewall problems.

COMMON DIAGNOSES:
- "No internet": ICMP loss + DNS failures → gateway/upstream problem
- "Slow browsing": DNS resolution >200ms → DNS server or path problem
- "Intermittent drops": Periodic retx bursts → WiFi interference or congestion
- "Can ping but can't browse": ICMP works, TCP RST on 443 → firewall/proxy

## Pre-Identified Issues
{pre_identified_issues_json}

## Focus Flows
{focus_flows_json}

## Capture Statistics
{summary_data_json}

## Data Truncations
{truncations_json}
```

### 16.3 DNS Pack Prompt

```
## Analysis Pack: DNS Troubleshooting

This capture focused on DNS traffic (UDP/TCP port 53) to diagnose name resolution.

PAY ATTENTION TO:
- Response time distribution: avg, median, P95. P95 >300ms is poor.
- NXDOMAIN ratio: >10% may indicate misconfigured services or DGA malware.
- SERVFAIL and REFUSED: Any count >0 = server-side DNS problems.
- Resolver IPs: Queries to unexpected resolvers = DNS hijacking or misconfig.
- Query type breakdown: High TXT/ANY volume from client = possible DNS tunneling.
- Slow domains: Which specific domains have worst resolution times?

COMMON DIAGNOSES:
- "Slow page loads, fast once loaded": High P95 → resolver latency
- "Some sites work, some don't": NXDOMAIN for specific domains → filtering/propagation
- "Intermittently slow DNS": Bimodal response times → primary/fallback split
- "Unexpected resolver": Queries to 1.1.1.1 when configured for 8.8.8.8 → hardcoded DNS

DNS tunneling/exfiltration: Only flag at MEDIUM+ confidence with: (a) queries to single
unusual domain, (b) encoded-looking subdomains, (c) high query volume. One long subdomain
is not enough.

## Pre-Identified Issues
{pre_identified_issues_json}

## Focus Flows
{focus_flows_json}

## Capture Statistics
{summary_data_json}

## Data Truncations
{truncations_json}
```

### 16.4 HTTPS/Web Pack Prompt

```
## Analysis Pack: HTTPS / Web Troubleshooting

This capture focused on HTTP/HTTPS traffic (ports 80, 443, 8080) to diagnose web
and API performance.

PAY ATTENTION TO:
- TCP retransmission rate: >1% is poor for web.
- Per-conversation retransmissions: Single degraded flow among healthy ones →
  server-side or path-specific, not local WiFi.
- Zero windows: Receiver can't consume fast enough. Common on constrained devices.
- RST ratio: connection_resets / connection_attempts. >10% abnormal.
- Throughput stability: High variance = inconsistent experience.
- TLS versions: 1.0/1.1 deprecated. May indicate outdated client/server.
- TLS SNI: Identify which services the device connects to.

COMMON DIAGNOSES:
- "Slow pages": High retx on large flows → WiFi/path congestion
- "Timeouts": SYN without SYN-ACK → unreachable or firewall
- "Mixed fast/slow": Some conversations healthy, some not → server-specific
- "Connection resets": High RST → server rejecting or load balancer issue

## Pre-Identified Issues
{pre_identified_issues_json}

## Focus Flows
{focus_flows_json}

## Capture Statistics
{summary_data_json}

## Data Truncations
{truncations_json}
```

### 16.5 Streaming/Video Pack Prompt

```
## Analysis Pack: Streaming / Video Debug

This capture targeted video streaming traffic to diagnose buffering, quality drops,
and playback interruptions.

PAY ATTENTION TO:
- Throughput timeline (MOST IMPORTANT for streaming):
  · Dips below 2 Mbps = below SD floor
  · Dips below 5 Mbps = below HD floor
  · Dips below 15 Mbps = below 4K floor
  · Dips lasting >3 seconds likely cause visible rebuffering
  · interesting_windows already flags these
- Retransmission rate: 0.5% threshold (tighter than web) — streaming clients
  have tight buffering deadlines.
- Dominant flow: Largest by bytes is almost certainly the media stream.
  Examine its retransmission count specifically.
- CDN patterns in DNS: akamai, cloudfront, fastly, edgecast, cdn.*, manifest.*
  Multiple CDN domains may indicate ABR switching or multi-CDN.
- UDP traffic: Large flows to port 443 = likely QUIC. Loss manifests differently.
- Throughput asymmetry: A→B >> B→A = download (expected). ~symmetric = video call.

COMMON DIAGNOSES:
- "Buffering every few seconds": Periodic throughput dips + retx → WiFi congestion
- "Starts HD then drops to SD": Decreasing throughput → competing traffic
- "Works then suddenly freezes": Throughput cliff → WiFi disassociation or outage
- "Audio fine, video freezes": Retx on large flow only → media segments retransmitted

IMPORTANT: You cannot determine ABR decisions from capture alone. Say "throughput fell
below the typical HD threshold" not "the player downshifted to SD."

## Pre-Identified Issues
{pre_identified_issues_json}

## Focus Flows
{focus_flows_json}

## Capture Statistics
{summary_data_json}

## Data Truncations
{truncations_json}
```

### 16.6 Security/Anomaly Pack Prompt

```
## Analysis Pack: Security / Anomaly Scan

This capture recorded ALL traffic to detect unexpected, suspicious, or anomalous behavior.

PAY ATTENTION TO:
- Unexpected endpoints: LAN devices (192.168.4.x) connecting to unusual IPs/ports.
- DNS anomalies:
  · Queries to non-configured resolvers
  · Long subdomain labels (>50 chars) → possible tunneling
  · High TXT query volume → possible exfiltration
- Port scanning: Single source → many destination ports rapidly.
- Network scanning: Single source → many destination IPs.
- Non-RFC1918 source IPs on LAN: Should not exist = spoofing.
- Suspicious ports: 4444, 31337, 1337, 6667/6697 (only with other indicators).

IMPORTANT RULES FOR SECURITY:
- Do NOT flag normal HTTPS to major services as suspicious
- Do NOT flag NTP, mDNS, SSDP, DHCP as anomalous
- DO flag unexpected plaintext protocols (telnet, FTP, HTTP on non-standard ports)
- CONFIDENCE must be MEDIUM+ for security findings. LOW confidence security should
  go in insufficient_evidence framed as "worth investigating"
- Distinguish "unusual" (LOW) from "malicious" (needs HIGH evidence)

COMMON DIAGNOSES:
- "Smart TV phoning home": Many tracking/analytics domains → expected but notable
- "IoT scanning": Single device → many LAN IPs → possibly compromised
- "DNS exfiltration": High-entropy subdomain queries to single domain → investigate
- "Rogue DHCP": Offers from unexpected IP → infrastructure problem

## Pre-Identified Issues
{pre_identified_issues_json}

## Focus Flows
{focus_flows_json}

## Capture Statistics
{summary_data_json}

## Data Truncations
{truncations_json}
```

### 16.7 Comparative Analysis Prompt

```
## Comparative Analysis

Compare two captures to explain what changed.

BASELINE: "{baseline_label}"
- Duration: {baseline_duration}s, {baseline_packets} packets
- Captured: {baseline_time}

SUBJECT: "{subject_label}"
- Duration: {subject_duration}s, {subject_packets} packets
- Captured: {subject_time}

## Pre-Computed Deltas
{deltas_json}

## Baseline Statistics
{baseline_summary_json}

## Subject Statistics
{subject_summary_json}

YOUR TASK:
1. Explain what changed in plain language.
2. For each degraded metric, explain magnitude and likely impact.
3. If different packs or BPF filters, note direct comparison may mislead.
4. If durations differ >50%, note rates/averages are more reliable than absolute counts.
5. Produce findings referencing BOTH captures. Cite "baseline.tcp_health.retransmission_rate_pct"
   and "subject.tcp_health.retransmission_rate_pct".
```

---

## Appendix A: tshark Extraction Commands

| Section | Command |
|---|---|
| Protocol hierarchy | `tshark -r {pcap} -q -z io,phs` |
| TCP conversations | `tshark -r {pcap} -q -z conv,tcp` |
| UDP conversations | `tshark -r {pcap} -q -z conv,udp` |
| Expert info | `tshark -r {pcap} -q -z expert` |
| Throughput | `tshark -r {pcap} -q -z io,stat,1` |
| Endpoints | `tshark -r {pcap} -q -z endpoints,ip` |
| DNS | `tshark -r {pcap} -T fields -e frame.time_relative -e dns.qry.name -e dns.qry.type -e dns.flags.response -e dns.flags.rcode -e dns.time -e ip.dst -Y "dns" -E header=y -E separator=\t` |
| ICMP | `tshark -r {pcap} -T fields -e frame.time_relative -e icmp.type -e icmp.code -e ip.src -e ip.dst -e icmp.resp_time -Y "icmp" -E header=y -E separator=\t` |
| TLS ClientHello | `tshark -r {pcap} -T fields -e tls.handshake.extensions_server_name -e ip.dst -e tcp.dstport -e tls.handshake.version -Y "tls.handshake.type == 1" -E header=y -E separator=\t` |
| TCP flags | `tshark -r {pcap} -T fields -e tcp.flags.syn -e tcp.flags.fin -e tcp.flags.reset -Y "tcp"` |

## Appendix B: Domain Sanitization

```python
_PROMPT_INJECTION_PATTERNS = re.compile(
    r"(ignore.previous|system:|<\||\bprompt\b.*\binjection\b|"
    r"\bassistant\b.*\bresponse\b|\bhuman\b:|\buser\b:)", re.IGNORECASE)

def sanitize_domain(domain: str) -> str | None:
    cleaned = "".join(c for c in domain if c.isprintable())
    if len(cleaned) > 253: cleaned = cleaned[:253]
    if _PROMPT_INJECTION_PATTERNS.search(cleaned): return None
    if any(len(label) > 63 for label in cleaned.split(".")): return None
    return cleaned
```

## Appendix C: Companion Specs

This master spec supersedes the following documents. They remain in the repo for historical context but should not be treated as authoritative where they conflict:

- `capture-v2-spec.md` — Original product & technical architecture
- `capture-v2-ux-spec.md` — Original UX design spec
- `ai-analysis-framework.md` — AI analysis framework (incorporated into sections 8-9 and 16)
- `rpi5-performance-guide.md` — RPi 5 optimization (incorporated into sections 6, 7, and 11)
