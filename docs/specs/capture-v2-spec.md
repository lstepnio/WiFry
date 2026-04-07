# Packet Capture System v2 — Product & Technical Design Spec

**Status:** Draft
**Author:** WiFry Engineering
**Date:** 2026-04-07
**Target:** WiFry v0.2.x

---

## 1. Problem Statement

The current capture module is a thin wrapper around `tshark -w`. It starts a capture, stops it, and optionally sends the raw stats to an AI. This works for quick one-offs but fails at what users actually need: a **troubleshooting workflow** that guides them from symptom to root cause without overwhelming a Raspberry Pi 5's 8 GB RAM and SD card.

### Current Gaps

| Gap | Impact |
|-----|--------|
| No rolling capture — must decide "start" before the problem occurs | Misses transient issues; user must reproduce the fault |
| No capture size/time rotation | SD card fills up on long runs |
| No concurrent capture limit | 5 simultaneous tshark processes can OOM the RPi |
| AI receives raw tshark stat dumps truncated to 3000 chars | Analysis quality degrades on large captures; no structure |
| No purpose-driven capture modes | User must know BPF syntax to filter for DNS, streaming, etc. |
| No automatic retention policy | Old captures accumulate until manual delete or factory reset |
| Single flat pcap per capture | Can't preserve a window around an event without keeping everything |

### Design Principles

1. **Capture always, analyze selectively.** The system should be recording before the user knows there's a problem.
2. **Extract small, send small.** AI never sees raw pcap. It sees structured statistical summaries.
3. **RPi-first.** Every design choice assumes 8 GB RAM, quad-core ARM, and a 32-128 GB SD card.
4. **One-click troubleshooting.** The common case should be: pick a mode, hit start, get a diagnosis.

---

## 2. Recommended End-to-End Workflow

### User Journey

```
[1] User opens Captures tab
         |
[2] Sees "Quick Capture" cards:    [3] Or sees "Background Capture"
    - Connectivity Check                toggle (rolling ring buffer
    - DNS Troubleshoot                  running continuously)
    - Streaming/Video Debug
    - Security Scan
    - Custom (existing advanced form)
         |
[4] Picks "Streaming/Video Debug"
         |
[5] System starts a focused capture:
    - BPF: tcp port 80 or tcp port 443 or udp portrange 1024-65535
    - Analysis pack: streaming
    - Duration: 60s default, adjustable
    - Ring buffer: 5 x 10MB files (50MB max)
         |
[6] Capture runs. UI shows:
    - Live file size + packet count estimate
    - Elapsed time / remaining time
    - Active ring buffer segment indicator
         |
[7] User stops (or duration expires)
         |
[8] Post-processing pipeline runs automatically:
    a. Merge ring buffer segments into single pcap (if needed)
    b. Extract statistics via tshark (pack-specific queries)
    c. Build structured summary JSON
    d. Optionally trigger AI analysis
         |
[9] User sees Results view:
    - Structured stats dashboard (no AI needed)
    - "Get AI Diagnosis" button for deeper analysis
    - Download pcap button
    - Link to session (if active)
```

### Background Capture (Roadmap)

A persistent ring-buffer capture that runs whenever the AP is active. When the user reports an issue or an anomaly is detected, the system "snapshots" the last N seconds of traffic into a preserved capture for analysis.

---

## 3. Feature Phasing

### Phase 1: MVP (Immediate — this PR cycle)

| Feature | Description | Effort |
|---------|-------------|--------|
| **Analysis Packs** | 5 predefined capture+analysis modes with BPF, tshark stat queries, and AI focus areas baked in | M |
| **Ring-buffer capture** | Use `dumpcap -b` for file rotation during capture; merge on stop | M |
| **Structured stat extraction** | Replace raw tshark dump with typed JSON summaries per analysis pack | M |
| **Concurrent capture limit** | Max 2 simultaneous captures (1 per interface recommended) | S |
| **Auto-retention** | Keep last 20 captures / 500 MB total; prune oldest on new capture start | S |
| **Post-processing pipeline** | Automatic stat extraction on capture completion (no manual "Analyze" step for stats) | M |
| **Capture progress UX** | Elapsed timer, estimated file size, ring buffer segment indicator | S |

### Phase 2: Next (v0.3.x)

| Feature | Description |
|---------|-------------|
| **Background capture** | Always-on ring buffer (dumpcap) that runs when AP is active; configurable retention window (30s-5min) |
| **Snapshot preserve** | "Preserve last 30s" button that copies ring buffer segments to a named capture |
| **Comparative analysis** | Compare two captures (before/after impairment) side-by-side |
| **Capture templates** | Save custom filter+duration+pack combos as reusable templates |
| **Stats-only mode** | Extract and display stats without keeping the pcap file (saves disk) |

### Phase 3: Roadmap (v0.4+)

| Feature | Description |
|---------|-------------|
| **Anomaly-triggered preserve** | Automatically snapshot background capture when: retransmission rate spikes, DNS failures detected, or streaming buffer stalls observed |
| **Streaming QoE correlation** | Cross-reference capture stats with HLS/DASH segment timing from the stream proxy |
| **Distributed capture** | Capture on both AP interface and upstream simultaneously; merge timeline |
| **pcapng migration** | Move from pcap to pcapng for per-packet comments and interface metadata |
| **Export to Wireshark cloud** | Upload filtered pcap slices to CloudShark for team collaboration |

---

## 4. Backend Architecture

### 4.1 Capture Engine

**Responsibility:** Start, monitor, stop, and rotate packet captures.

```
CaptureEngine
├── start_capture(config) → CaptureInfo
│   ├── validate resource budget (concurrent limit, disk space)
│   ├── select tool: dumpcap (ring buffer) or tshark (single file)
│   ├── launch subprocess
│   └── register monitor task
├── stop_capture(id) → CaptureInfo
│   ├── SIGTERM → 5s → SIGKILL
│   ├── fix permissions (chown/chmod)
│   └── trigger post-processing pipeline
├── get_live_stats(id) → {file_size, elapsed, segment_index}
└── cleanup_stale() → reconcile on restart
```

**Key change from v1:** The engine no longer just writes a single pcap. It manages ring-buffer segments and merges them on stop.

**Concurrent capture semaphore:**
```python
_capture_semaphore = asyncio.Semaphore(2)  # max 2 simultaneous

async def start_capture(...):
    if not _capture_semaphore.locked() or _capture_semaphore._value > 0:
        async with _capture_semaphore:
            ...
    else:
        raise HTTPException(429, "Maximum concurrent captures reached (2). Stop a running capture first.")
```

### 4.2 Post-Processing Pipeline

Runs automatically when a capture completes or is stopped.

```
PostProcessor
├── merge_segments(capture_id)
│   └── mergecap -w merged.pcap seg_*.pcap (if ring buffer)
├── extract_stats(capture_id, analysis_pack)
│   └── run pack-specific tshark queries → structured JSON
├── compute_summary(capture_id, stats)
│   └── derive key metrics without AI (retx rate, top talkers, DNS failure %, etc.)
├── save_summary(capture_id, summary)
│   └── write {id}.summary.json
└── enforce_retention()
    └── prune oldest captures if over 20 count or 500 MB total
```

**File layout after post-processing:**
```
captures/
├── {id}.json               # capture metadata (existing)
├── {id}.pcap               # merged pcap (or single file)
├── {id}.summary.json       # structured stats + computed metrics (NEW)
├── {id}.analysis.json      # AI analysis (on-demand, existing)
└── {id}_segments/          # ring buffer segments (deleted after merge, or kept if >100MB)
    ├── {id}_00001.pcap
    ├── {id}_00002.pcap
    └── ...
```

### 4.3 AI Analysis Pipeline

**Core change:** AI never receives raw tshark output. It receives the structured summary JSON produced by post-processing.

```
AI Pipeline (on-demand, user-triggered)
├── load {id}.summary.json
├── select AI prompt template for analysis_pack
├── build prompt:
│   ├── system: "You are a network diagnostician. Given structured capture statistics..."
│   ├── context: analysis_pack description + what to look for
│   └── data: summary JSON (typically 2-8 KB, never >20 KB)
├── call provider (Claude / GPT)
├── parse structured response
├── save {id}.analysis.json
└── link to session as artifact
```

**Why this is better:**
- Deterministic input size (~5 KB vs unbounded tshark dumps)
- AI sees typed numbers (retransmission_rate: 3.2%) not raw text parsing
- Same summary powers the non-AI stats dashboard
- Cheaper per-call (fewer input tokens)

### 4.4 Storage & Retention Model

**Retention policy (auto-enforced):**

| Rule | Threshold | Action |
|------|-----------|--------|
| Max capture count | 20 | Delete oldest completed capture |
| Max total capture storage | 500 MB | Delete oldest completed capture |
| Max single capture age | 7 days | Delete on next capture start |
| Running captures | exempt | Never auto-deleted |
| Session-linked captures | exempt while session active | Deleted when session discarded |

**Disk budget estimation for RPi 5 (32 GB SD):**
```
System + OS:              ~4 GB
WiFry application:        ~200 MB
Captures (capped):        500 MB
Sessions + artifacts:     ~200 MB
Logs + runtime state:     ~100 MB
─────────────────────────
Total WiFry footprint:    ~1 GB (3% of 32 GB card)
Headroom for user data:   ~27 GB
```

### 4.5 Resource Protection for RPi 5

| Protection | Implementation |
|------------|---------------|
| Max 2 concurrent captures | asyncio.Semaphore(2) checked before subprocess launch |
| Per-capture file size ceiling | 100 MB default (down from 500 MB); adjustable to 200 MB max |
| Ring buffer segment size | 10 MB per segment; max 10 segments = 100 MB |
| tshark process nice level | `nice -n 10` prefix to deprioritize vs. AP/routing |
| Post-processing serialization | One post-processing pipeline at a time (asyncio.Lock) |
| Disk space pre-check | Before starting capture, verify 200 MB free on captures volume |
| AI rate limit | Max 1 AI analysis call per 30 seconds (prevent rapid re-analyze spam) |
| Stats extraction timeout | 60s per tshark query; 5-minute total timeout for full pack |

---

## 5. dumpcap vs tshark — When to Use Which

| Criterion | dumpcap | tshark |
|-----------|---------|--------|
| **Purpose** | Capture packets to disk | Capture + decode + analyze |
| **Memory footprint** | ~5 MB RSS | ~30-80 MB RSS (protocol dissectors loaded) |
| **Ring buffer support** | Native: `-b filesize:10240 -b files:10` | Supported but heavier; loads dissectors unnecessarily |
| **CPU usage during capture** | Minimal — raw write only | Higher — decodes every packet even with `-w` |
| **Stat extraction** | Cannot (capture-only tool) | Full: `-z io,phs`, `-z conv,tcp`, `-z expert`, etc. |
| **BPF filter** | Yes (`-f`) | Yes (`-f` for capture, `-Y` for display) |
| **Runs as root** | Yes (needs packet socket) | Yes |
| **Output format** | pcap / pcapng | pcap / pcapng + many text formats |

### Decision

**Use dumpcap for capture. Use tshark for post-processing.**

```
Capture phase:    dumpcap -i wlan0 -b filesize:10240 -b files:10 -f "tcp" -w /captures/{id}.pcap
                  └─ low memory, low CPU, native ring buffer

Stop / Complete:  mergecap -w /captures/{id}.pcap /captures/{id}_*.pcap
                  └─ combine ring segments into single file

Stats phase:      tshark -r /captures/{id}.pcap -q -z io,phs
                  tshark -r /captures/{id}.pcap -q -z conv,tcp
                  tshark -r /captures/{id}.pcap -q -z expert
                  └─ full dissection on completed file only
```

**Why not tshark for capture?**
- On RPi 5, `tshark -w` loads all dissectors into memory even when just writing raw packets. This wastes 30-80 MB RAM per capture process. With 2 concurrent captures, that's 160 MB of unnecessary overhead.
- `dumpcap` is the same capture engine Wireshark uses internally. It's purpose-built for this.
- Ring buffer rotation with `dumpcap -b` is battle-tested; tshark's equivalent works but is heavier.

**Migration path:** Replace `tshark -i ... -w` with `dumpcap -i ... -w` in `capture.py`. All post-processing tshark commands remain unchanged.

---

## 6. AI Without Raw pcap Ingestion

### The Problem

Today's pipeline extracts 5 tshark stat outputs, truncates each to 3000 chars, and concatenates them into the AI prompt. This has issues:
- Raw tshark table output is hard for the LLM to parse reliably
- Truncation may cut off the most relevant data (e.g., top talkers at the bottom)
- No structure — the AI must infer what the numbers mean
- Scales poorly with capture size

### The Solution: Structured Summary JSON

Post-processing produces a typed JSON summary that is both the stats dashboard data and the AI input.

```json
{
  "capture_id": "a1b2c3d4e5f6",
  "analysis_pack": "streaming",
  "duration_secs": 58.3,
  "total_packets": 24531,
  "total_bytes": 18420156,

  "protocols": {
    "TCP": {"packets": 22100, "bytes": 17800000, "pct": 90.1},
    "UDP": {"packets": 2200, "bytes": 580000, "pct": 9.0},
    "ICMP": {"packets": 231, "bytes": 40156, "pct": 0.9}
  },

  "tcp_health": {
    "retransmission_count": 312,
    "retransmission_rate_pct": 1.41,
    "duplicate_ack_count": 89,
    "zero_window_count": 3,
    "rst_count": 12,
    "avg_rtt_ms": null
  },

  "top_conversations": [
    {
      "src": "192.168.4.10", "src_port": 54321,
      "dst": "104.16.132.229", "dst_port": 443,
      "packets": 8500, "bytes": 6200000,
      "retransmissions": 45
    }
  ],

  "dns": {
    "total_queries": 142,
    "unique_domains": 38,
    "nxdomain_count": 2,
    "slow_queries_over_500ms": 5,
    "top_queried": [
      {"domain": "manifest.prod.boltdns.net", "count": 12},
      {"domain": "cdn.example.com", "count": 8}
    ]
  },

  "throughput": {
    "avg_mbps": 2.53,
    "peak_mbps": 8.71,
    "min_mbps": 0.12,
    "intervals": [
      {"second": 0, "bytes": 312000},
      {"second": 1, "bytes": 845000}
    ]
  },

  "expert_alerts": {
    "errors": 15,
    "warnings": 89,
    "notes": 342,
    "top_alerts": [
      {"severity": "warning", "group": "sequence", "message": "TCP retransmission", "count": 312},
      {"severity": "note", "group": "sequence", "message": "TCP duplicate ACK", "count": 89}
    ]
  }
}
```

**Size:** Typically 3-8 KB. Max ~20 KB for very busy captures. This fits comfortably in any LLM context.

### AI Prompt Template (per analysis pack)

```
System: You are a network diagnostician for a WiFi test appliance.
        You receive structured packet capture statistics (never raw pcap).
        Respond with JSON matching the schema below.

User:   ## Analysis Pack: Streaming/Video Debug
        The user captured traffic to diagnose video streaming issues.
        Pay special attention to:
        - TCP retransmission rates (>1% is concerning for streaming)
        - Throughput stability (look for drops that would cause rebuffering)
        - DNS resolution for CDN domains
        - Large flows that look like media segments

        ## Capture Statistics
        {summary_json}
```

---

## 7. Analysis Packs

Each pack defines: a BPF filter, specific tshark stat queries, summary fields to extract, and AI focus guidance.

### Pack Definitions

#### 7.1 Connectivity

**Purpose:** "Is the network working? Can I reach the internet?"

| Property | Value |
|----------|-------|
| BPF filter | `icmp or (tcp[tcpflags] & tcp-syn != 0) or udp port 53` |
| Default duration | 30 seconds |
| Key stats | ICMP echo/reply success rate, DNS resolution time, TCP SYN/SYN-ACK latency, gateway reachability |
| tshark queries | `-z io,phs`, `-z expert`, custom DNS field extraction, ICMP round-trip |
| AI focus | Packet loss, unreachable hosts, DNS failures, default gateway health |
| When to use | "Nothing works" / first-pass triage |

#### 7.2 DNS

**Purpose:** "Are DNS lookups working correctly and quickly?"

| Property | Value |
|----------|-------|
| BPF filter | `udp port 53 or tcp port 53` |
| Default duration | 60 seconds |
| Key stats | Query count, response time distribution, NXDOMAIN count, SERVFAIL count, unique domains, query type breakdown |
| tshark queries | DNS field extraction (`-T fields -e dns.qry.name -e dns.time -e dns.flags.rcode`), `-z io,stat,1` |
| AI focus | Slow lookups (>200ms), failed lookups, unusual query patterns, DNS hijacking indicators |
| When to use | Apps slow to load, intermittent connectivity |

#### 7.3 HTTPS / Web

**Purpose:** "Are web requests completing quickly and correctly?"

| Property | Value |
|----------|-------|
| BPF filter | `tcp port 80 or tcp port 443 or tcp port 8080` |
| Default duration | 60 seconds |
| Key stats | TCP connection setup time, TLS handshake indicators, retransmission rate, RST count, throughput per conversation, HTTP error indicators |
| tshark queries | `-z conv,tcp`, `-z expert`, `-z io,stat,1`, TLS client hello extraction |
| AI focus | Slow connections, high retransmission on specific flows, RST storms, certificate issues |
| When to use | Web browsing slow, API calls failing |

#### 7.4 Streaming / Video

**Purpose:** "Why is the video buffering, freezing, or low quality?"

| Property | Value |
|----------|-------|
| BPF filter | `tcp port 80 or tcp port 443 or udp portrange 1024-65535` |
| Default duration | 120 seconds |
| Key stats | Throughput timeline (1-sec intervals), retransmission rate, top flows by bytes (media segment detection), DNS for CDN domains, jitter estimation from packet inter-arrival |
| tshark queries | `-z conv,tcp`, `-z io,stat,1`, `-z expert`, DNS extraction, UDP jitter via `frame.time_delta` |
| AI focus | Throughput dips below typical ABR ladder thresholds (2/5/10/15 Mbps), retransmission bursts correlated with throughput drops, CDN switching patterns, UDP packet loss for QUIC/RTP |
| When to use | Buffering, pixelation, quality drops |

#### 7.5 Security / Anomaly

**Purpose:** "Is there unexpected traffic, rogue DNS, or suspicious patterns?"

| Property | Value |
|----------|-------|
| BPF filter | (none — capture all) |
| Default duration | 60 seconds |
| Key stats | Unique src/dst IPs, unusual ports, DNS to non-configured resolvers, broadcast/multicast volume, SYN scan patterns, non-RFC1918 source IPs on LAN |
| tshark queries | `-z endpoints,ip`, `-z conv,tcp`, `-z io,phs`, DNS destination IP extraction |
| AI focus | Unexpected outbound connections, DNS exfiltration patterns, port scanning, ARP spoofing indicators, traffic to known-bad IP ranges |
| When to use | Security audit, unexpected bandwidth usage |

### Custom (Advanced)

Retains the existing advanced form: manual interface, BPF, duration, packet limits. Defaults to "General" analysis with all stat queries.

---

## 8. Session Model

### Current State

Sessions exist (`TestSession`) and captures auto-link as artifacts. But the linkage is thin — just a metadata pointer. There's no way to:
- See all captures within a session on a timeline
- Correlate capture stats with impairment changes
- Compare "before impairment" vs "during impairment" captures

### Proposed Model

```
TestSession
├── id, name, status, tags, notes
├── device: {serial, model, ip}
├── timeline: [
│     {t: "10:00:00", event: "session_started"},
│     {t: "10:00:15", event: "capture_started", capture_id: "abc", pack: "streaming"},
│     {t: "10:01:05", event: "impairment_applied", profile: "3G Congested"},
│     {t: "10:02:15", event: "capture_completed", capture_id: "abc", summary: {...}},
│     {t: "10:02:20", event: "capture_started", capture_id: "def", pack: "streaming"},
│     {t: "10:03:25", event: "anomaly_detected", type: "retx_spike", capture_id: "def"},
│     {t: "10:04:20", event: "capture_completed", capture_id: "def", summary: {...}},
│     {t: "10:04:25", event: "impairment_cleared"},
│   ]
├── captures: [
│     {id: "abc", pack: "streaming", summary: {...}, analysis: {...}},
│     {id: "def", pack: "streaming", summary: {...}, analysis: {...}},
│   ]
└── comparative_notes: "Retransmission rate went from 0.3% to 4.7% under 3G Congested profile"
```

**Timeline events** are appended by each service:
- `capture.py` → capture_started, capture_completed
- `session_manager.py` → session_started, session_completed, session_paused
- `impairments.py` / `network_config.py` → impairment_applied, impairment_cleared
- Future: anomaly detector → anomaly_detected

**Implementation approach:**
- Add `timeline: List[TimelineEvent]` to `TestSession` model
- Each service calls `session_manager.record_event(event_type, data)` instead of raw artifact linking
- Captures still link as artifacts (backward compatible), but the timeline is the primary UX surface

---

## 9. Risks, Tradeoffs, and Design Decisions

### Decision 1: dumpcap for capture, tshark for analysis

**Risk:** Two different tools means two things to install and debug.
**Mitigation:** Both ship with the `tshark` apt package. dumpcap is always present where tshark is.
**Tradeoff accepted:** Slightly more complex subprocess management in exchange for 60% less RAM per capture.

### Decision 2: Ring buffer as default (not optional)

**Risk:** Ring buffer means older packets are overwritten. A 100 MB capture with 10 x 10 MB segments only keeps ~100 MB of data even on a 5-minute capture.
**Mitigation:** For troubleshooting, the most recent packets are almost always more relevant. The file size ceiling protects the SD card. Users who need full captures can use Custom mode with ring buffer disabled.
**Tradeoff accepted:** Lose oldest packets in exchange for bounded disk usage.

### Decision 3: Max 2 concurrent captures

**Risk:** Power users may want per-interface + background capture simultaneously.
**Mitigation:** 2 is the practical limit for RPi 5 — each dumpcap process + post-processing tshark needs ~50 MB combined. Background capture (phase 2) will count as one of the 2 slots.
**Tradeoff accepted:** Simplicity and stability over flexibility.

### Decision 4: Structured summary as AI input (no raw stats)

**Risk:** Structured extraction may miss edge cases that raw tshark output would reveal.
**Mitigation:** The structured summary is a superset of what the current truncated 3000-char dumps provide. Each analysis pack defines specific additional tshark field extractions. The raw pcap is always available for manual Wireshark analysis.
**Tradeoff accepted:** Slightly less AI flexibility in exchange for deterministic, small, cheap AI input.

### Decision 5: Auto-retention with 20 captures / 500 MB limit

**Risk:** User loses old captures they wanted to keep.
**Mitigation:** Session-linked captures are exempt from auto-pruning while the session is active. Completed sessions should be bundled/exported before discarding. A warning notification fires when auto-pruning occurs.
**Tradeoff accepted:** Disk health over unlimited history.

### Decision 6: No pcapng in MVP

**Risk:** pcap format lacks per-packet comments and multi-interface metadata.
**Mitigation:** pcapng is fully supported by dumpcap/tshark/mergecap. We can migrate in phase 3 without breaking the pipeline. For MVP, pcap is simpler and more universally compatible (every tool reads it).
**Tradeoff accepted:** Compatibility now, richer format later.

### Risk: SD card write amplification

**Concern:** Continuous ring-buffer capture generates sustained sequential writes. SD cards have limited write endurance.
**Mitigation:**
- Default captures are short (30-120s). Not continuous.
- Background capture (phase 2) will require an explicit opt-in warning about SD card wear.
- External USB storage support already exists in storage.py — recommend USB for background capture.
- Captures written to `/var/lib/wifry/captures` which can be pointed to USB mount.

### Risk: mergecap failure on large ring buffer

**Concern:** Merging 10 x 10 MB segments requires reading all into memory.
**Mitigation:** mergecap is streaming — it reads packets sequentially, not all at once. 100 MB merge uses ~10 MB RSS. Tested up to 500 MB with no issues on RPi 4.

---

## 10. Acceptance Criteria & Implementation Notes

### AC-1: Analysis Packs

```
GIVEN the user opens the Captures tab
WHEN they see the Quick Capture section
THEN they see 5 cards: Connectivity, DNS, HTTPS/Web, Streaming/Video, Security
AND each card shows a one-line description of what it checks
AND clicking a card opens a pre-filled capture form with pack-specific defaults
AND the user can adjust duration before starting
```

**Implementation:**
- New `AnalysisPack` model in `backend/app/models/capture.py`:
  ```python
  class AnalysisPack(str, Enum):
      CONNECTIVITY = "connectivity"
      DNS = "dns"
      HTTPS = "https"
      STREAMING = "streaming"
      SECURITY = "security"
      CUSTOM = "custom"
  ```
- `ANALYSIS_PACK_CONFIGS` dict mapping pack → BPF, duration, max_size, stat_queries, ai_focus
- `StartCaptureRequest` gains optional `analysis_pack` field (default: CUSTOM)
- Frontend: new `QuickCapture` component above the existing advanced form

### AC-2: dumpcap Ring Buffer

```
GIVEN a capture is started (any pack or custom)
WHEN ring_buffer is enabled (default: true for packs, configurable for custom)
THEN the system uses dumpcap with -b filesize:10240 -b files:10
AND live monitoring shows current segment index and total size
AND on stop/complete, segments are merged into a single {id}.pcap via mergecap
AND segments are deleted after successful merge
```

**Implementation:**
- Replace `tshark -i ... -w` with `dumpcap -i ... -w` in `capture.py`
- Add ring buffer args: `-b filesize:{segment_size_kb} -b files:{max_files}`
- dumpcap names segments automatically: `{id}_00001_...pcap`, `{id}_00002_...pcap`
- Add `_merge_segments()` function using `mergecap -w {id}.pcap {id}_*.pcap`
- Add `ring_buffer: bool = True` and `segment_size_mb: int = 10` to `StartCaptureRequest`
- Track segment count in CaptureInfo: `segment_count: int = 0`

### AC-3: Structured Summary Extraction

```
GIVEN a capture has completed or been stopped
WHEN post-processing runs
THEN the system extracts pack-specific stats via tshark
AND produces a typed JSON summary saved as {id}.summary.json
AND the summary is displayed in the UI without requiring AI
AND the summary is <=20 KB
```

**Implementation:**
- New `backend/app/services/capture_stats.py`:
  - `extract_stats(pcap_path, pack) -> dict` — runs tshark queries per pack
  - `parse_protocol_hierarchy(raw) -> dict` — parse `io,phs` output to typed dict
  - `parse_tcp_conversations(raw) -> list` — parse `conv,tcp` to typed list
  - `parse_expert_info(raw) -> dict` — parse `expert` to severity counts + top alerts
  - `parse_dns_queries(raw) -> dict` — parse DNS fields to typed summary
  - `parse_io_stats(raw) -> dict` — parse `io,stat,1` to throughput timeline
- New `CapturesSummary` Pydantic model matching the JSON schema in section 6
- Post-processing triggered automatically in `_monitor_capture()` after finalization

### AC-4: Concurrent Capture Limit

```
GIVEN 2 captures are already running
WHEN the user tries to start a third
THEN the API returns 429 with message "Maximum concurrent captures reached (2)"
AND the UI shows the error via toast notification
AND the user can stop an existing capture to free a slot
```

**Implementation:**
- Add `_capture_semaphore = asyncio.Semaphore(2)` in `capture.py`
- Check before launching subprocess; raise `HTTPException(429)` if at limit
- Frontend: display running capture count and disable "Start" button at limit

### AC-5: Auto-Retention

```
GIVEN the retention policy is 20 captures / 500 MB
WHEN a new capture completes post-processing
THEN the system checks total capture count and disk usage
AND if over limit, deletes the oldest completed capture(s) not linked to an active session
AND emits a notification: "Auto-cleaned {n} old capture(s) to free {x} MB"
```

**Implementation:**
- New `_enforce_retention()` in `capture.py`, called at end of post-processing
- Query all captures sorted by `started_at` ascending
- Skip: status=RUNNING, or linked to active session
- Delete until under both thresholds
- Emit event to audit_log

### AC-6: AI Analysis Uses Summary JSON

```
GIVEN a capture has a .summary.json file
WHEN the user clicks "Get AI Diagnosis"
THEN the AI receives the structured summary JSON (not raw tshark output)
AND the AI prompt includes the analysis pack context
AND the response is the same structured format as today
AND total AI input is <20 KB
```

**Implementation:**
- Modify `ai_analyzer.py`:
  - Replace `_extract_stats()` with `load summary.json`
  - Replace raw string concatenation with `json.dumps(summary, indent=2)`
  - Use pack-specific system prompt templates
- Keep the existing `AnalysisResult` response model (backward compatible)

### AC-7: Capture Progress UX

```
GIVEN a capture is running
WHEN the user views the capture list
THEN they see: elapsed time (counting up), file size (live), ring buffer segment indicator (e.g., "Segment 3/10")
AND a stop button
AND an estimated packet rate (bytes/sec derived from file size delta)
```

**Implementation:**
- Extend `CaptureInfo` with: `elapsed_secs: float`, `segment_index: int`, `bytes_per_sec: float`
- `_monitor_capture()` computes these from file size deltas between polls
- Frontend: update `CaptureManager` running state display

---

## 11. Migration Path from v1

The spec is designed for incremental migration:

1. **Keep all existing API endpoints unchanged** — new features are additive
2. **`analysis_pack` defaults to `CUSTOM`** — existing captures work exactly as before
3. **Ring buffer defaults to `true` for packs, `false` for custom** — no behavior change for advanced users
4. **Summary extraction is automatic but optional for AI** — existing "Analyze" button still works
5. **Retention is opt-out** — add `WIFRY_CAPTURE_RETENTION_ENABLED=false` env var escape hatch

### API Changes (Additive Only)

| Change | Backward Compatible |
|--------|-------------------|
| `StartCaptureRequest.analysis_pack` field (optional, default CUSTOM) | Yes |
| `StartCaptureRequest.ring_buffer` field (optional, default varies) | Yes |
| `StartCaptureRequest.segment_size_mb` field (optional, default 10) | Yes |
| `CaptureInfo.analysis_pack` field | Yes (null for old captures) |
| `CaptureInfo.segment_count` field | Yes (0 for old captures) |
| `CaptureInfo.summary_available` field | Yes (false for old captures) |
| `GET /api/v1/captures/{id}/summary` new endpoint | New endpoint, no break |
| `GET /api/v1/captures/packs` new endpoint (list available packs) | New endpoint, no break |
| Lower default `max_file_size_mb` from 50 to 100 (ring buffer total) | Non-breaking, more generous |

---

## 12. Implementation Order

Recommended sequence for a single development cycle:

```
Week 1:  Analysis pack model + configs (backend)
         dumpcap switch + ring buffer (backend)
         Post-processing pipeline skeleton (backend)

Week 2:  Structured stat extraction + parsers (backend)
         Summary JSON generation (backend)
         Concurrent capture semaphore (backend)
         Auto-retention (backend)

Week 3:  Quick Capture cards (frontend)
         Capture progress UX improvements (frontend)
         Stats dashboard (frontend, renders summary.json)
         AI prompt migration to use summary.json (backend)

Week 4:  Integration testing on RPi 5 hardware
         Performance profiling (dumpcap RSS, merge time, post-processing duration)
         Edge case testing (disk full, process crash, concurrent limits)
         Session timeline events (backend + frontend)
```

---

## Appendix A: tshark Stat Queries by Pack

| Query | Connectivity | DNS | HTTPS | Streaming | Security |
|-------|:-:|:-:|:-:|:-:|:-:|
| `-z io,phs` (protocol hierarchy) | x | | x | x | x |
| `-z conv,tcp` (TCP conversations) | | | x | x | x |
| `-z conv,udp` (UDP conversations) | | x | | x | x |
| `-z io,stat,1` (throughput/sec) | | | x | x | |
| `-z expert` (retx, errors) | x | | x | x | |
| `-z endpoints,ip` (unique IPs) | x | | | | x |
| DNS field extraction | x | x | | x | x |
| ICMP field extraction | x | | | | |
| TCP handshake timing | x | | x | | |

## Appendix B: Resource Budget per Capture (RPi 5)

| Phase | CPU | RAM | Disk I/O | Duration |
|-------|-----|-----|----------|----------|
| **Capture** (dumpcap) | ~5% 1 core | ~5 MB | Sequential write, ~1-10 MB/s | User-defined |
| **Merge** (mergecap) | ~20% 1 core | ~10 MB | Read all segments + write merged | ~2s per 100 MB |
| **Stats** (tshark x5) | ~80% 1 core | ~50-80 MB | Read merged pcap x5 | ~5-15s per 100 MB |
| **AI call** | ~0% | ~1 MB | Network only | 2-10s |
| **Total post-processing** | — | ~80 MB peak | — | ~10-30s typical |

## Appendix C: Config Defaults

```python
# backend/app/models/capture.py additions
CAPTURE_DEFAULTS = {
    "max_concurrent": 2,
    "retention_max_count": 20,
    "retention_max_bytes": 500 * 1024 * 1024,  # 500 MB
    "retention_max_age_days": 7,
    "ring_buffer_segment_mb": 10,
    "ring_buffer_max_segments": 10,
    "post_processing_timeout_secs": 300,
    "ai_rate_limit_secs": 30,
    "disk_space_min_mb": 200,
}
```
