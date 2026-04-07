# Packet Capture v2 — UX Design Spec

**Status:** Draft
**Date:** 2026-04-07
**Companion:** `capture-v2-spec.md` (technical architecture)

---

## 1. Information Architecture

The Captures tab transforms from a single flat list into a three-zone layout:

```
┌─────────────────────────────────────────────────────────────────┐
│  CAPTURES TAB                                                   │
│                                                                 │
│  ┌─ Zone A: Start ────────────────────────────────────────────┐ │
│  │  Quick Capture cards (5 packs) + "Custom Capture" toggle   │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌─ Zone B: Active ───────────────────────────────────────────┐ │
│  │  Running capture(s) with live progress — 0-2 items         │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌─ Zone C: History ──────────────────────────────────────────┐ │
│  │  Completed captures with inline stats + drill-in           │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Zone A** is always visible unless a capture is actively being configured (then the form expands in-place). **Zone B** appears only when captures are running. **Zone C** is always visible.

This replaces the current design where the "New Capture" form occludes the capture list and there is no visual separation between running and completed captures.

---

## 2. Page Flow

### 2.1 Starting a New Capture — Quick Path

```
User sees 5 pack cards in a horizontal row
    │
    ├─ Clicks "Streaming / Video"
    │
    ▼
Card expands into a slim config bar:
┌──────────────────────────────────────────────────┐
│  Streaming / Video                     [Start]   │
│  Duration: [120s ▾]   Interface: [wlan0 ▾]       │
│  Captures HTTP/HTTPS + UDP media traffic.        │
│  BPF: tcp port 80 or tcp port 443 or udp ...     │
│  Ring buffer: 10 × 10 MB segments                │
│                                    [Cancel]       │
└──────────────────────────────────────────────────┘
    │
    ├─ User adjusts duration if desired
    ├─ Clicks [Start]
    │
    ▼
Card collapses. Capture appears in Zone B (Active).
```

**Key UX decisions:**
- No separate page or modal. Configuration happens inline below the card.
- Only 2 fields exposed: **Duration** and **Interface**. Everything else is pre-configured by the pack.
- The BPF and ring buffer config are shown as read-only context, not editable fields. This builds trust ("I can see what it's doing") without creating decision fatigue.
- [Cancel] returns to the card grid with no state change.

### 2.2 Starting a New Capture — Custom Path

```
User clicks "Custom Capture" text link below the cards
    │
    ▼
Full form panel appears (similar to current, but improved):
┌──────────────────────────────────────────────────┐
│  Custom Capture                                  │
│                                                  │
│  Capture Target                                  │
│  Interface: [wlan0 ▾]   Name: [optional label]   │
│                                                  │
│  Filters                                         │
│  ┌ Preset: [None ▾] ──────────────────────────┐  │
│  │ Host: [          ]  Port: [     ]          │  │
│  │ Protocol: [Any ▾]  Direction: [Both ▾]     │  │
│  │ Custom BPF: [                            ] │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  Limits                                          │
│  Duration: [300s]  Max size: [100 MB]            │
│  Ring buffer: [on ▾]  Segments: [10 × 10 MB]    │
│                                                  │
│                       [Cancel]  [Start Capture]  │
└──────────────────────────────────────────────────┘
```

**Changes from current form:**
- "Preset" dropdown at top of filters lets the user seed fields from a pack, then customize
- Ring buffer controls are visible and explained
- Max packets field removed from default view (moved to an "Advanced" disclosure, it's rarely useful and creates confusion)
- Direction filter added (was in the model but not exposed in UI)
- Clearer field grouping with labeled sections

### 2.3 Monitoring an Active Capture

Zone B renders one card per running capture:

```
┌──────────────────────────────────────────────────┐
│  ● Recording    Streaming / Video                │
│  wlan0 · tcp port 80 or tcp port 443 or udp...   │
│                                                  │
│  ┌──────────────────────────────────────────┐    │
│  │ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░  54s / 120s │    │
│  └──────────────────────────────────────────┘    │
│                                                  │
│  12.4 MB captured · Segment 3/10 · ~2,100 pkt/s │
│                                                  │
│                                        [Stop]    │
└──────────────────────────────────────────────────┘
```

**Elements:**
- **Status indicator**: pulsing green dot + "Recording" label (matches SessionPanel's recording indicator pattern)
- **Pack name**: shown prominently so the user remembers what mode is active
- **Interface + BPF**: single line, truncated with ellipsis, full text on hover/title
- **Progress bar**: elapsed / total duration, filled proportionally. Uses blue-600 fill.
- **Live stats row**: file size (updated every 1s), ring buffer segment indicator, estimated packet rate
- **Stop button**: red-bordered, right-aligned, uses the existing danger-border button pattern

**If 2 captures are running**, both cards stack vertically. If at max (2), the Quick Capture cards in Zone A show a disabled state with tooltip: "Stop a running capture to start a new one."

### 2.4 Reviewing Completed Captures

Zone C shows the capture history as a list. Each row is richer than the current design:

```
┌──────────────────────────────────────────────────┐
│  capture-a1b2c3   Streaming / Video   completed  │
│  wlan0 · 58s · 24,531 packets · 18.4 MB         │
│  Today 14:32                                     │
│                                                  │
│  ┌─ Quick Stats ─────────────────────────────┐   │
│  │ Retx: 1.4%  │ Throughput: 2.5 Mbps avg   │   │
│  │ DNS queries: 142  │ Top: manifest.prod... │   │
│  └───────────────────────────────────────────┘   │
│                                                  │
│  [View Details]  [AI Diagnosis]  [Download pcap] │
│                                           [Delete]│
└──────────────────────────────────────────────────┘
```

**Key differences from current:**
- **Quick Stats inline**: The structured summary (from post-processing) shows 2-4 key metrics right in the list, before the user clicks anything. This answers "was this capture interesting?" without drilling in.
- **Pack badge**: Shows which analysis pack was used, helping the user remember context.
- **Relative time**: "Today 14:32" instead of full ISO timestamp.
- **[View Details]** replaces [Analyze] as the primary action. This opens the detail view (section 2.5).
- **[AI Diagnosis]** is a separate, clearly labeled secondary action.

**Sort order:** Most recent first (current behavior, keep it).

**Bulk actions:** "Clear All" button in the section header (already exists). Consider adding "Export All" in phase 2.

### 2.5 Detail View (Stats + AI Analysis)

Clicking [View Details] on a completed capture navigates to an inline detail view within the Captures tab (same pattern as SessionPanel's list → detail navigation):

```
┌──────────────────────────────────────────────────┐
│  ← Back to Captures                              │
│                                                  │
│  capture-a1b2c3    Streaming / Video   completed │
│  wlan0 · 58s · 24,531 packets · 18.4 MB         │
│  Started: Today 14:32 · Ended: Today 14:33       │
│  BPF: tcp port 80 or tcp port 443 or udp...      │
│                                                  │
│  [Download pcap]  [AI Diagnosis]  [Delete]        │
│                                                  │
├──────────────────────────────────────────────────┤
│                                                  │
│  CAPTURE STATISTICS                              │
│  (auto-extracted, no AI needed)                  │
│                                                  │
│  ┌─ Protocol Breakdown ─────────────────────┐    │
│  │ TCP  ████████████████████████░░  90.1%   │    │
│  │ UDP  ██░░░░░░░░░░░░░░░░░░░░░░░   9.0%   │    │
│  │ ICMP ░░░░░░░░░░░░░░░░░░░░░░░░░   0.9%   │    │
│  └──────────────────────────────────────────┘    │
│                                                  │
│  ┌─ TCP Health ─────────────────────────────┐    │
│  │ Retransmissions   312 (1.4%)       ⚠     │    │
│  │ Duplicate ACKs     89              ─     │    │
│  │ Zero Windows        3              ─     │    │
│  │ RST Count          12              ─     │    │
│  └──────────────────────────────────────────┘    │
│                                                  │
│  ┌─ Throughput ─────────────────────────────┐    │
│  │  8┤          ╱╲                          │    │
│  │  6┤    ╱╲  ╱    ╲    ╱╲                  │    │
│  │  4┤  ╱    ╲╱      ╲╱    ╲╱╲              │    │
│  │  2┤╱                        ╲───         │    │
│  │  0┼──────────────────────────────        │    │
│  │   0s   10s   20s   30s   40s   50s       │    │
│  │  Avg: 2.5 Mbps  Peak: 8.7 Mbps          │    │
│  └──────────────────────────────────────────┘    │
│                                                  │
│  ┌─ Top Conversations ──────────────────────┐    │
│  │ 192.168.4.10:54321 → 104.16.132.229:443 │    │
│  │   8,500 pkts · 6.2 MB · 45 retx (0.5%)  │    │
│  │ 192.168.4.10:54999 → 151.101.1.69:443   │    │
│  │   3,200 pkts · 2.1 MB · 12 retx (0.4%)  │    │
│  └──────────────────────────────────────────┘    │
│                                                  │
│  ┌─ DNS ────────────────────────────────────┐    │
│  │ 142 queries · 38 unique domains          │    │
│  │ 2 NXDOMAIN · 5 slow (>500ms)            │    │
│  │ Top: manifest.prod.boltdns.net (12)      │    │
│  └──────────────────────────────────────────┘    │
│                                                  │
├──────────────────────────────────────────────────┤
│                                                  │
│  AI DIAGNOSIS                                    │
│  (on-demand — costs 1 API call)                  │
│                                                  │
│  [Get AI Diagnosis]                              │
│                                                  │
│  ─── or, if already analyzed: ───                │
│                                                  │
│  (see section 2.6 below)                         │
│                                                  │
└──────────────────────────────────────────────────┘
```

**Design rationale:**
- Stats are shown **before** AI analysis. The user gets immediate value from structured data without waiting for an API call.
- AI is positioned as a deeper "second opinion," not the primary output.
- Throughput chart uses a simple ASCII-style sparkline. In implementation, use a lightweight inline SVG (no chart library needed — just polyline from the `intervals` array in summary.json).
- TCP Health uses a status indicator: green check (good), yellow warning (concerning), red alert (bad). Thresholds: retransmission >1% = warning, >5% = alert.

### 2.6 AI Diagnosis Presentation

When the user clicks [Get AI Diagnosis] or views a previously analyzed capture:

```
┌──────────────────────────────────────────────────┐
│  AI DIAGNOSIS                                    │
│  Claude · claude-sonnet · 2,341 tokens           │
│  Analyzed: Today 14:35                           │
│                                                  │
│  ┌─ Summary ────────────────────────────────┐    │
│  │ Moderate network health issues detected. │    │
│  │ TCP retransmission rate of 1.4% is above │    │
│  │ the 1% threshold for stable streaming,   │    │
│  │ with throughput dips correlating to       │    │
│  │ retransmission bursts at 22s and 38s.    │    │
│  └──────────────────────────────────────────┘    │
│                                                  │
│  ISSUES FOUND (3)                                │
│                                                  │
│  ┌─ ⚠ HIGH ─ Retransmissions ──────────────┐    │
│  │                                          │    │
│  │  TCP retransmission rate of 1.4% on the  │    │
│  │  primary media flow (104.16.132.229:443) │    │
│  │  exceeds the 1% threshold for reliable   │    │
│  │  ABR streaming.                          │    │
│  │                                          │    │
│  │  Evidence:                               │    │
│  │  · 312 retransmissions / 22,100 TCP pkts │    │
│  │  · Concentrated at 22s and 38s marks     │    │
│  │  · Correlates with throughput dips below  │    │
│  │    2 Mbps (see throughput chart above)    │    │
│  │                                          │    │
│  │  Affected flows:                         │    │
│  │  192.168.4.10:54321 → 104.16.132.229:443│    │
│  │                                          │    │
│  │  Recommendation:                         │    │
│  │  Check for RF interference or reduce the │    │
│  │  impairment loss rate. Current loss may   │    │
│  │  be triggering TCP congestion control.   │    │
│  │                                          │    │
│  │  Confidence: HIGH                        │    │
│  │  Based on: retransmission count, timing  │    │
│  │  correlation with throughput data         │    │
│  └──────────────────────────────────────────┘    │
│                                                  │
│  ┌─ ─ MEDIUM ─ DNS Latency ────────────────┐    │
│  │  ...                                     │    │
│  └──────────────────────────────────────────┘    │
│                                                  │
│  ┌─ ─ LOW ─ Unusual Port Activity ─────────┐    │
│  │  ...                                     │    │
│  └──────────────────────────────────────────┘    │
│                                                  │
│  [Re-analyze]  [Copy to Clipboard]               │
│                                                  │
│  ┌─ How to read this ──────────────────────┐     │
│  │ This analysis is generated by AI from   │     │
│  │ structured capture statistics — not from │     │
│  │ raw packet data. It identifies patterns  │     │
│  │ but may miss edge cases. Download the    │     │
│  │ pcap for manual verification in          │     │
│  │ Wireshark if needed.                     │     │
│  └─────────────────────────────────────────┘     │
└──────────────────────────────────────────────────┘
```

**Confidence & evidence presentation (section 8 of your request):**

Each AI issue includes:
1. **Evidence section** — specific numbers from the capture stats that support the finding. This grounds the AI's claim in observable data.
2. **Affected flows** — exact IP:port pairs so the user can verify in Wireshark.
3. **Confidence level** — HIGH / MEDIUM / LOW, with a one-line explanation of what data supports it.
4. **Cross-references** — "see throughput chart above" links the AI narrative to the user's own stat view.

The "How to read this" disclosure at the bottom appears collapsed by default, expandable. It sets expectations about AI limitations without undermining trust in the output.

### 2.7 Preserving / Exporting Artifacts

Capture artifacts flow into sessions through the existing auto-link mechanism. The UX additions:

**On the capture detail view:**
- If a session is active: `Linked to session: "STB-123 Buffering Test"` badge with link
- If no session is active: `Not linked to a session` with a `[Link to Session]` button that opens a dropdown of active/recent sessions

**On the session detail view (existing SessionPanel):**
- Captures appear in the artifact list with their pack badge and quick stats
- Impairment changes appear on the timeline alongside capture start/stop events
- This is the "evidence package" view for the troubleshooting session

**Export:**
- [Download pcap] on capture detail (existing)
- Session bundle already includes linked captures (existing)
- Future: "Export stats as CSV" for the structured summary data

---

## 3. Capture Modes

Four modes, presented as a clear hierarchy:

| Mode | Who it's for | Entry point | Duration | Ring buffer |
|------|-------------|-------------|----------|-------------|
| **Quick Capture** | Most users, most of the time | Pack cards in Zone A | 30-120s per pack | On, 10 × 10 MB |
| **Custom Capture** | Power users who need BPF control | "Custom Capture" link below cards | User-defined, max 1hr | User choice |
| **Background Watch** | Phase 2 — always-on monitoring | Toggle in capture header | Continuous | On, last 5 min |
| **Issue Reproduction** | Phase 2 — capture + impairment combo | Session workflow entry | Matched to test duration | On |

### Quick Capture (MVP)
One-click (well, two-click) capture with pack-specific filters and analysis. This is the primary workflow.

### Custom Capture (MVP)
The existing advanced form, cleaned up. For users who know their BPF, need specific limits, or want to capture traffic that doesn't fit a pack.

### Background Watch (Phase 2)
A persistent low-overhead capture that runs whenever the AP is active. Displayed as a toggle in the Captures header:

```
┌──────────────────────────────────────────────────┐
│  Captures                   Background: [  OFF]  │
│                                                  │
```

When ON, a subtle persistent indicator shows in the header. When an issue is noticed, the user clicks "Preserve last 60s" to snapshot the ring buffer into a named capture for analysis.

### Issue Reproduction (Phase 2)
Integrated with the Session workflow: "Start capture → apply impairment → observe → stop capture → compare." This is a guided multi-step flow that lives in the Session detail view, not the Captures tab.

---

## 4. Presets (Analysis Packs)

### Card Layout

Five cards in a horizontal scrollable row (mobile) or grid (desktop):

```
┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
│ Connect │ │  DNS    │ │  HTTPS  │ │Streaming│ │Security │
│  ivity  │ │         │ │  / Web  │ │ / Video │ │  Scan   │
│         │ │ 60s     │ │ 60s     │ │ 120s    │ │ 60s     │
│ 30s     │ │ port 53 │ │ 80/443  │ │ 80/443  │ │ all     │
│ ICMP+DNS│ │         │ │         │ │ + UDP   │ │ traffic │
│ + SYN   │ │         │ │         │ │         │ │         │
└─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘
```

### Card Anatomy

Each card contains:
1. **Icon area** — A simple monochrome icon or emoji-free symbol (use CSS shapes or inline SVG)
2. **Pack name** — Bold, 1-2 words
3. **Duration default** — e.g., "60s"
4. **One-line scope** — e.g., "HTTP/HTTPS traffic on ports 80 and 443"
5. **Hover state** — border-blue-500 highlight

### Per-Pack Detail

#### Connectivity Check
- **Card label:** Connectivity
- **Subtitle:** Can you reach the network?
- **Scope line:** ICMP, DNS lookups, TCP handshakes
- **Default duration:** 30s
- **When to use hint (shown in expanded config bar):** "Use this first when nothing is working. Checks basic reachability, DNS, and TCP connection setup."

#### DNS Troubleshoot
- **Card label:** DNS
- **Subtitle:** Are lookups fast and correct?
- **Scope line:** All DNS traffic (port 53)
- **Default duration:** 60s
- **When to use hint:** "Use when apps are slow to load or connections fail intermittently. Checks for slow, failed, or hijacked DNS responses."

#### HTTPS / Web
- **Card label:** HTTPS / Web
- **Subtitle:** Are web requests completing?
- **Scope line:** HTTP and HTTPS traffic (ports 80, 443)
- **Default duration:** 60s
- **When to use hint:** "Use when web pages load slowly or API calls fail. Checks TCP health, TLS setup, and retransmission rates on web traffic."

#### Streaming / Video
- **Card label:** Streaming / Video
- **Subtitle:** Why is the video buffering?
- **Scope line:** HTTP/HTTPS + UDP media traffic
- **Default duration:** 120s
- **When to use hint:** "Use during active video playback. Checks throughput stability, retransmission bursts, CDN resolution, and media flow health."

#### Security Scan
- **Card label:** Security
- **Subtitle:** Is there unexpected traffic?
- **Scope line:** All traffic (no filter)
- **Default duration:** 60s
- **When to use hint:** "Use to audit what's on the network. Checks for unexpected connections, unusual ports, rogue DNS, and scan patterns."

---

## 5. Wireframe-Level UI Layout

### Full Captures Tab — Default State (no running captures)

```
╔══════════════════════════════════════════════════════════════╗
║  Packet Captures                          SessionBadge      ║
║  Capture and analyze network traffic to diagnose issues.    ║
╠══════════════════════════════════════════════════════════════╣
║                                                             ║
║  QUICK CAPTURE                                              ║
║  Pick a troubleshooting mode to start a focused capture.    ║
║                                                             ║
║  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐   ║
║  │Connectiv. │ │   DNS     │ │HTTPS/Web  │ │Streaming  │   ║
║  │Can you    │ │Are lookups│ │Are web    │ │Why is the │   ║
║  │reach the  │ │fast and   │ │requests   │ │video      │   ║
║  │network?   │ │correct?   │ │completing?│ │buffering? │   ║
║  │   30s     │ │   60s     │ │   60s     │ │   120s    │   ║
║  └───────────┘ └───────────┘ └───────────┘ └───────────┘   ║
║                                                             ║
║  ┌───────────┐                                              ║
║  │ Security  │     Need more control? Custom Capture →      ║
║  │Is there   │                                              ║
║  │unexpected │                                              ║
║  │traffic?   │                                              ║
║  │   60s     │                                              ║
║  └───────────┘                                              ║
║                                                             ║
╠══════════════════════════════════════════════════════════════╣
║                                                             ║
║  CAPTURE HISTORY                             [Clear All]    ║
║                                                             ║
║  ┌──────────────────────────────────────────────────────┐   ║
║  │  capture-a1b2  Streaming / Video  ●completed         │   ║
║  │  wlan0 · 58s · 24,531 pkts · 18.4 MB · Today 14:32  │   ║
║  │  Retx: 1.4%  Throughput: 2.5 Mbps avg               │   ║
║  │  [View Details]  [AI Diagnosis]  [Download]  [Delete]│   ║
║  └──────────────────────────────────────────────────────┘   ║
║                                                             ║
║  ┌──────────────────────────────────────────────────────┐   ║
║  │  dns-check     DNS              ●completed           │   ║
║  │  wlan0 · 60s · 4,102 pkts · 1.2 MB · Today 14:28    │   ║
║  │  Queries: 89  NXDOMAIN: 0  Slow (>500ms): 1         │   ║
║  │  [View Details]  [AI Diagnosis]  [Download]  [Delete]│   ║
║  └──────────────────────────────────────────────────────┘   ║
║                                                             ║
║  ┌──────────────────────────────────────────────────────┐   ║
║  │  custom-cap    Custom           ●stopped             │   ║
║  │  wlan0 · 12s · 1,230 pkts · 0.8 MB · Yesterday      │   ║
║  │  No summary available (legacy capture)               │   ║
║  │  [View Details]  [AI Diagnosis]  [Download]  [Delete]│   ║
║  └──────────────────────────────────────────────────────┘   ║
║                                                             ║
║  No more captures. Auto-retention keeps the last 20.        ║
║                                                             ║
╚══════════════════════════════════════════════════════════════╝
```

### Full Captures Tab — Active Capture State

```
╔══════════════════════════════════════════════════════════════╗
║  Packet Captures                          SessionBadge      ║
║  Capture and analyze network traffic to diagnose issues.    ║
╠══════════════════════════════════════════════════════════════╣
║                                                             ║
║  QUICK CAPTURE                                              ║
║  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐             ║
║  │ dim  │ │ dim  │ │ dim  │ │ dim  │ │ dim  │  ← dimmed   ║
║  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘  if at max  ║
║                                                             ║
╠══════════════════════════════════════════════════════════════╣
║                                                             ║
║  ACTIVE CAPTURES (1/2)                                      ║
║                                                             ║
║  ┌──────────────────────────────────────────────────────┐   ║
║  │  ● Recording   Streaming / Video                     │   ║
║  │  wlan0 · tcp port 80 or tcp port 443 or udp...       │   ║
║  │                                                      │   ║
║  │  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░  54s / 120s         │   ║
║  │                                                      │   ║
║  │  12.4 MB · Segment 3 of 10 · ~2.1k pkt/s            │   ║
║  │                                              [Stop]  │   ║
║  └──────────────────────────────────────────────────────┘   ║
║                                                             ║
╠══════════════════════════════════════════════════════════════╣
║                                                             ║
║  CAPTURE HISTORY                             [Clear All]    ║
║  ... (same as above)                                        ║
╚══════════════════════════════════════════════════════════════╝
```

---

## 6. Labels, Grouping, Microcopy, Defaults, and Warnings

### Section Headers

| Section | Label | Helper text |
|---------|-------|-------------|
| Top header | "Packet Captures" | "Capture and analyze network traffic to diagnose issues." |
| Quick Capture | "Quick Capture" | "Pick a troubleshooting mode to start a focused capture." |
| Active | "Active Captures (N/2)" | (none — the progress card is self-explanatory) |
| History | "Capture History" | (none — the list is self-explanatory) |
| Detail stats | "Capture Statistics" | "Auto-extracted from the pcap — no AI needed." |
| AI section | "AI Diagnosis" | "Uses your configured AI provider. Costs 1 API call (~2K tokens)." |

### Form Fields

| Field | Label | Placeholder | Default | Helper text |
|-------|-------|-------------|---------|-------------|
| Interface | "Interface" | — | "wlan0" | (none — advanced users know) |
| Name | "Name" | "optional label" | auto-generated | "Leave blank for auto-name" |
| Duration | "Duration" | — | Pack-specific | "How long to capture. Traffic stops automatically." |
| Host | "Host IP" | "192.168.4.10" | (empty) | "Filter to a specific device" |
| Port | "Port" | "443" | (empty) | (none) |
| Protocol | "Protocol" | — | "Any" | (none) |
| Custom BPF | "Custom BPF" | "tcp port 443 and host 192.168.4.10" | (empty) | "Overrides all other filters" |
| Ring buffer | "Ring buffer" | — | On for packs | "Rotates capture files to limit disk usage" |
| Max size | "Max capture size" | — | "100 MB" | "Total across all segments" |

### Warnings & Guardrails

| Trigger | Warning | Placement |
|---------|---------|-----------|
| 2 captures already running | "Maximum concurrent captures reached. Stop a running capture to start a new one." | Toast notification + disabled cards |
| Disk space < 200 MB free | "Low disk space ({n} MB free). Consider deleting old captures or connecting USB storage." | Yellow banner above Quick Capture |
| Capture duration > 600s | "Long captures generate large files. Consider using a ring buffer to limit disk usage." | Inline under Duration field |
| Custom BPF entered | "Custom BPF overrides Host, Port, and Protocol filters above." | Inline under BPF field |
| AI not configured | "AI analysis requires an API key. Configure in System → Settings." | Shown in place of [Get AI Diagnosis] button |
| Auto-retention pruned captures | "Auto-cleaned {n} old capture(s) to free {x} MB." | Toast notification |
| Legacy capture (no summary) | "No summary available. This capture was created before stats extraction was added. Run AI Diagnosis for analysis." | Inline in history row |

### Status Badges

| Status | Label | Style | Notes |
|--------|-------|-------|-------|
| RUNNING | "recording" | Green dot + green text | Animated pulse on dot |
| COMPLETED | "completed" | Green badge | Existing pattern |
| STOPPED | "stopped" | Yellow badge | User manually stopped |
| ERROR | "error" | Red badge | Capture process failed |
| PROCESSING | "processing" | Blue badge with spinner | NEW — during post-processing |

---

## 7. Timeline / History / Session UX

### Capture History in the Captures Tab

The history list in Zone C serves as both a log and a quick-access tool. Key UX properties:

- **Sorted by recency** — newest first, always
- **Pack badge visible** — the colored pack indicator tells you at a glance what kind of capture it was
- **Inline stats** — 2-4 metrics from the summary, pack-specific:
  - Connectivity: "Reachable: yes · DNS: ok · Avg latency: 12ms"
  - DNS: "Queries: 89 · NXDOMAIN: 0 · Slow: 1"
  - HTTPS: "Retx: 0.8% · Connections: 14 · RSTs: 0"
  - Streaming: "Retx: 1.4% · Throughput: 2.5 Mbps avg"
  - Security: "Unique IPs: 23 · Unusual ports: 2 · Rogue DNS: 0"
  - Custom/Legacy: "Packets: {n} · Size: {x}" (minimal)
- **No pagination** — auto-retention limits to 20 captures; scroll is fine

### Session Integration

When a session is active, the Captures tab shows a context banner:

```
┌──────────────────────────────────────────────────────┐
│  ● Recording to session: "STB-123 Buffering Test"    │
│  Captures will auto-link to this session.            │
└──────────────────────────────────────────────────────┘
```

In the Session detail view (existing SessionPanel), captures appear in the artifact list and the timeline:

```
Timeline:
  14:30  Session started
  14:31  Capture started — Streaming / Video (capture-a1b2)
  14:31  Impairment applied — 3G Congested (100ms delay, 2% loss)
  14:33  Capture completed — Retx: 1.4%, Throughput: 2.5 Mbps
  14:34  Impairment cleared
  14:35  Capture started — Streaming / Video (capture-c3d4)
  14:37  Capture completed — Retx: 0.2%, Throughput: 5.1 Mbps
  14:38  Session completed
```

This timeline is the key evidence surface for "what changed when" troubleshooting.

---

## 8. AI Confidence & Evidence Presentation

### Design Goals

Users of network diagnostic tools are skeptical of AI output. They need to:
1. **See the data the AI saw** — the stats dashboard is rendered before the AI section
2. **Verify specific claims** — each issue cites exact numbers from the capture
3. **Understand limitations** — the tool is transparent about what it can and can't do
4. **Act on recommendations** — each issue ends with a specific, actionable step

### Issue Card Structure

Every AI-generated issue follows this template:

```
┌─ SEVERITY ─ Category ───────────────────────────┐
│                                                  │
│  [Description — 2-3 sentences max]               │
│                                                  │
│  Evidence:                                       │
│  · [specific metric from capture stats]          │
│  · [correlation or pattern observed]             │
│                                                  │
│  Affected flows:                                 │
│  [IP:port → IP:port]                             │
│                                                  │
│  Recommendation:                                 │
│  [One specific action the user can take]         │
│                                                  │
│  Confidence: HIGH | MEDIUM | LOW                 │
│  Based on: [what data supports this conclusion]  │
│                                                  │
└──────────────────────────────────────────────────┘
```

### Confidence Levels

| Level | Meaning | When to use | Visual |
|-------|---------|-------------|--------|
| HIGH | Multiple corroborating data points | Retransmission rate + throughput correlation | Green "HIGH" badge |
| MEDIUM | Single clear signal | Elevated retransmission rate alone | Yellow "MEDIUM" badge |
| LOW | Inferred or circumstantial | Unusual port activity that may be benign | Gray "LOW" badge |

### Trust Signals

1. **Stats-first layout** — user sees raw numbers before AI interpretation
2. **"Evidence" section** — forces AI to cite its sources
3. **"Based on" line** — makes the reasoning chain visible
4. **Cross-references** — "see throughput chart above" creates a verifiable link
5. **Disclaimer** — expandable "How to read this" box:
   > "This analysis is generated by AI from structured capture statistics — not from raw packet inspection. It identifies patterns and anomalies but may miss edge cases that require manual analysis. Download the pcap and open it in Wireshark for full investigation."
6. **Provider transparency** — "Claude · claude-sonnet · 2,341 tokens" shown in the header

### Anti-patterns Avoided

- No "AI confidence: 87%" fake precision — confidence is categorical (HIGH/MEDIUM/LOW)
- No hiding the AI label — it's always clear this is AI-generated
- No presenting AI as authoritative — it's positioned as "diagnosis" not "verdict"
- No hallucination-prone free text — structured template constrains output

---

## 9. UX Mistakes to Avoid

### For Packet Capture Tools Specifically

| Mistake | Why it's bad | What to do instead |
|---------|-------------|-------------------|
| **Making the BPF field the primary input** | 90% of users don't know BPF. It signals "this tool is not for you." | Lead with Quick Capture cards. Hide BPF in Custom mode. |
| **Showing raw tshark output** | Users can't interpret protocol hierarchy tables. Even experts prefer summaries. | Show structured stats with visual indicators (bars, sparklines, status icons). |
| **Requiring AI for any useful output** | AI costs money, takes time, and may be unconfigured. Users give up. | Auto-extract stats on every capture. AI is the bonus layer, not the only layer. |
| **Starting a capture with no guidance on duration** | Users either capture too short (miss the issue) or too long (fill the disk). | Pack defaults are tuned per use case. Duration is prominent with sensible defaults. |
| **Hiding the capture filter after start** | User forgets what they're capturing and whether it's relevant to their issue. | Show BPF and pack name prominently on the active capture card. |
| **Flat list of captures with no context** | "capture-a1b2c3d4" means nothing a day later. | Show pack name, inline stats, and relative timestamps. |
| **Full-page AI loading spinner** | Analysis takes 3-10 seconds. A blocking spinner feels broken. | Show stats immediately. AI loads below in its own section with a contained spinner. |
| **Treating all captures as equally important** | Most captures are quick checks. A few are critical evidence. | Session-linked captures are visually distinguished. "Link to Session" action on others. |
| **No disk space awareness** | RPi has limited storage. Captures silently fail when disk is full. | Pre-check disk space before starting. Auto-retention with notifications. |
| **Letting users start unlimited concurrent captures** | 5 tshark processes will thrash the RPi. | Hard limit of 2 with clear messaging. Disable cards when at max. |
| **Modal dialogs for capture configuration** | Breaks flow. User can't see the capture list while configuring. | Inline expansion below the selected card. |
| **Separate "Analysis" page** | Navigation tax. User loses context switching between capture and its analysis. | Inline detail view with stats and AI on the same page (← Back navigation). |
| **Auto-running AI on every capture** | Wastes API credits on quick checks the user may not care about. | Stats are automatic. AI is on-demand with clear cost indication. |
| **No empty state guidance** | First-time user sees "No captures" and doesn't know what to do. | Empty state: "Start your first capture — pick a troubleshooting mode above, or use Custom Capture for full control." |

### General UX for Technical Tools

| Mistake | What to do instead |
|---------|-------------------|
| **Dumbing it down** | Respect the user's intelligence. Show real data, real units, real filters. Just organize it well. |
| **Tooltip overload** | Use inline helper text for fields that need explanation. Skip tooltips for obvious things. |
| **Hiding the "power user" path** | Always keep Custom Capture accessible. Don't gate it behind settings. |
| **Inconsistent status updates** | If file size updates every 1s, elapsed time should too. Mismatched cadence feels broken. |
| **Stale data on screen** | Poll running captures at 1-3s. Poll history at 5s. Never show a "running" capture that finished 30s ago. |

---

## Appendix A: Component Mapping

| UI Section | Current Component | Proposed Changes |
|------------|------------------|-----------------|
| Captures tab root | CaptureManager.tsx | Split into CaptureManager (orchestrator) + QuickCapture + ActiveCapture + CaptureHistory |
| Quick Capture cards | (new) | QuickCapture.tsx — card grid + inline config expansion |
| Active capture progress | Part of CaptureManager list | ActiveCapture.tsx — dedicated progress card |
| Capture history list | Part of CaptureManager list | CaptureHistory.tsx — enhanced rows with inline stats |
| Capture detail view | CaptureAnalysis.tsx (partial) | CaptureDetail.tsx — stats dashboard + AI section combined |
| AI analysis display | CaptureAnalysis.tsx | Merged into CaptureDetail.tsx as a section |

### Tailwind Patterns to Use

These patterns match the existing WiFry design system:

- **Card container:** `rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900`
- **Quick capture card:** `cursor-pointer rounded-lg border border-gray-200 bg-gray-50 p-4 transition-colors hover:border-blue-500 dark:border-gray-700 dark:bg-gray-800 dark:hover:border-blue-500`
- **Active card:** `rounded-lg border border-green-600 bg-green-950/30 p-4` (matches SessionPanel's active indicator)
- **Progress bar fill:** `h-2 rounded-full bg-blue-600` inside `h-2 w-full rounded-full bg-gray-700`
- **Section header:** `text-xs font-medium uppercase tracking-wide text-gray-500`
- **Stat value:** `text-2xl font-bold text-gray-900 dark:text-white` with `text-[10px] uppercase text-gray-500` label (matches SpeedTest pattern)

## Appendix B: Interaction States Summary

| State | Zone A (Quick Capture) | Zone B (Active) | Zone C (History) |
|-------|----------------------|-----------------|-----------------|
| No captures ever | Cards enabled | Hidden | Empty state message |
| 1 capture running | Cards enabled | 1 progress card | Previous captures |
| 2 captures running (max) | Cards dimmed + tooltip | 2 progress cards | Previous captures |
| Capture just completed | Cards enabled | Card transitions to history | New row at top with "NEW" badge (3s) |
| Post-processing | Cards enabled | "Processing..." status | (not yet visible) |
| Viewing detail | Hidden (detail view replaces) | Hidden | Hidden (detail view replaces) |
