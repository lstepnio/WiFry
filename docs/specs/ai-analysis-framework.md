# AI Analysis Framework for Packet Capture

**Status:** Draft
**Date:** 2026-04-07
**Companion specs:** `capture-v2-spec.md`, `capture-v2-ux-spec.md`

---

## 1. Design Philosophy

Three rules govern every AI interaction in WiFry:

1. **AI interprets; it never observes.** The AI sees structured statistical summaries derived from pcap by deterministic tshark queries. It never sees raw packets, hex dumps, or truncated tshark text. If the statistics are insufficient to answer a question, the AI says so.

2. **Every claim cites its source.** Each finding in an AI response must reference a specific field from the input summary JSON. "Retransmission rate is concerning" is not allowed. "TCP retransmission rate of 3.2% (312 of 22,100 TCP packets) exceeds the 1% threshold for reliable streaming" is required.

3. **Confidence is earned, not declared.** The AI classifies confidence as HIGH, MEDIUM, or LOW based on explicit rules tied to data completeness. It never produces percentages (fake precision) or unqualified assertions.

---

## 2. Analysis Pipeline

### 2.1 End-to-End Flow

```
Raw pcap on disk
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│  Stage 1: Deterministic Extraction (tshark)              │
│                                                          │
│  Run pack-specific tshark queries against merged pcap.   │
│  Parse text output into typed Python dicts.              │
│  No AI involved. Runs on every completed capture.        │
│                                                          │
│  Output: CaptureSummary JSON (~3-8 KB)                   │
│  Stored: {id}.summary.json                               │
└──────────────────┬───────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────┐
│  Stage 2: Interest Detection (deterministic rules)       │
│                                                          │
│  Score each summary field against pack-specific          │
│  thresholds. Identify "interesting" windows and flows.   │
│  Tag anomalies for AI attention.                         │
│                                                          │
│  Output: InterestAnnotations added to summary            │
│  (flags, anomaly_windows, focus_flows)                   │
└──────────────────┬───────────────────────────────────────┘
                   │
                   ▼  (user clicks "Get AI Diagnosis")
┌──────────────────────────────────────────────────────────┐
│  Stage 3: AI Interpretation (on-demand)                  │
│                                                          │
│  Select prompt template for analysis pack.               │
│  Inject CaptureSummary + InterestAnnotations as JSON.    │
│  Call Claude / GPT with structured output schema.        │
│  Validate response against guardrails.                   │
│                                                          │
│  Output: AnalysisResult JSON                             │
│  Stored: {id}.analysis.json                              │
└──────────────────────────────────────────────────────────┘
```

### 2.2 Why Three Stages?

| Stage | Cost | Latency | Runs when |
|-------|------|---------|-----------|
| Extraction | 0 (local tshark) | 5-15s | Every capture, automatically |
| Interest detection | 0 (local rules) | <100ms | Every capture, automatically |
| AI interpretation | $0.01-0.05 per call | 3-10s | On-demand only |

Stages 1-2 power the stats dashboard for free. Stage 3 is optional and user-triggered. This means a user who never configures an AI key still gets a useful capture tool.

---

## 3. Stage 1: Derived Artifacts

### 3.1 Artifact Types

Every completed capture produces exactly one `CaptureSummary` JSON. The fields present depend on the analysis pack. All packs produce the `meta` and `protocols` sections; pack-specific sections are added based on which tshark queries ran.

| Artifact section | Source tshark query | Present in packs | Typical size |
|---|---|---|---|
| `meta` | pcap header + `capinfos` | All | 200 bytes |
| `protocols` | `-z io,phs` | All | 300-500 bytes |
| `tcp_health` | `-z expert` + computation | Connectivity, HTTPS, Streaming | 200 bytes |
| `conversations` | `-z conv,tcp` and/or `-z conv,udp` | HTTPS, Streaming, Security | 500-2000 bytes |
| `dns` | `-T fields` DNS extraction | Connectivity, DNS, Streaming, Security | 300-1000 bytes |
| `throughput` | `-z io,stat,1` | HTTPS, Streaming | 500-2000 bytes |
| `expert_alerts` | `-z expert` | Connectivity, HTTPS, Streaming | 300-800 bytes |
| `icmp` | ICMP field extraction | Connectivity | 200-400 bytes |
| `endpoints` | `-z endpoints,ip` | Security | 300-1000 bytes |
| `tls_handshakes` | TLS ClientHello extraction | HTTPS, Security | 200-600 bytes |

### 3.2 CaptureSummary Schema

```python
class CaptureMeta(BaseModel):
    capture_id: str
    analysis_pack: str                    # "connectivity" | "dns" | "https" | "streaming" | "security" | "custom"
    interface: str
    bpf_filter: str
    started_at: str                       # ISO 8601
    stopped_at: str
    duration_secs: float
    total_packets: int
    total_bytes: int
    capture_file_size_bytes: int
    ring_buffer_segments: int

class ProtocolBreakdown(BaseModel):
    name: str                             # "TCP", "UDP", "ICMP", etc.
    packets: int
    bytes: int
    pct_packets: float                    # 0-100
    children: list["ProtocolBreakdown"]   # nested: TCP → TLS → HTTP2

class TcpHealth(BaseModel):
    retransmission_count: int
    retransmission_rate_pct: float        # retransmissions / total TCP packets * 100
    duplicate_ack_count: int
    zero_window_count: int
    rst_count: int
    syn_count: int
    fin_count: int
    connection_attempts: int              # SYN packets
    connection_completions: int           # SYN-ACK packets

class Conversation(BaseModel):
    src: str
    src_port: int
    dst: str
    dst_port: int
    protocol: str                         # "TCP" or "UDP"
    packets_a_to_b: int
    packets_b_to_a: int
    bytes_a_to_b: int
    bytes_b_to_a: int
    duration_secs: float | None
    retransmissions: int | None           # TCP only

class DnsSummary(BaseModel):
    total_queries: int
    total_responses: int
    unique_domains: int
    nxdomain_count: int
    servfail_count: int
    refused_count: int
    queries_over_500ms: int
    queries_over_1000ms: int
    avg_response_time_ms: float | None
    median_response_time_ms: float | None
    p95_response_time_ms: float | None
    query_type_breakdown: dict[str, int]  # {"A": 80, "AAAA": 40, "CNAME": 12}
    top_queried_domains: list[DnsDomainEntry]
    top_slow_domains: list[DnsDomainEntry]
    resolver_ips: list[str]               # which DNS servers were queried

class DnsDomainEntry(BaseModel):
    domain: str
    count: int
    avg_time_ms: float | None
    rcodes: dict[str, int]                # {"NoError": 10, "NXDomain": 2}

class ThroughputInterval(BaseModel):
    second: int                           # offset from capture start
    bytes: int
    packets: int

class ThroughputSummary(BaseModel):
    avg_bps: float
    peak_bps: float
    min_bps: float
    std_dev_bps: float                    # throughput variability
    intervals: list[ThroughputInterval]   # 1-second granularity

class ExpertAlert(BaseModel):
    severity: str                         # "error", "warning", "note", "chat"
    group: str                            # "sequence", "response", "request", "protocol", "malformed"
    message: str
    count: int

class ExpertSummary(BaseModel):
    error_count: int
    warning_count: int
    note_count: int
    top_alerts: list[ExpertAlert]         # top 20 by count

class IcmpSummary(BaseModel):
    echo_request_count: int
    echo_reply_count: int
    unreachable_count: int
    ttl_exceeded_count: int
    avg_rtt_ms: float | None
    min_rtt_ms: float | None
    max_rtt_ms: float | None
    loss_rate_pct: float | None           # (requests - replies) / requests * 100
    targets: list[IcmpTarget]

class IcmpTarget(BaseModel):
    ip: str
    requests: int
    replies: int
    avg_rtt_ms: float | None

class EndpointEntry(BaseModel):
    ip: str
    packets: int
    bytes: int
    is_rfc1918: bool                      # private IP range?

class TlsHandshake(BaseModel):
    server_name: str                      # SNI from ClientHello
    dst_ip: str
    dst_port: int
    tls_version: str                      # "TLSv1.2", "TLSv1.3"
    count: int                            # how many connections to this SNI

class CaptureSummary(BaseModel):
    meta: CaptureMeta
    protocols: list[ProtocolBreakdown]
    tcp_health: TcpHealth | None
    conversations: list[Conversation]     # top 20 by bytes
    dns: DnsSummary | None
    throughput: ThroughputSummary | None
    expert_alerts: ExpertSummary | None
    icmp: IcmpSummary | None
    endpoints: list[EndpointEntry] | None # top 30 by bytes
    tls_handshakes: list[TlsHandshake] | None
    interest: InterestAnnotations | None  # added by stage 2
```

### 3.3 Size Budget

The summary is capped at 20 KB for AI input. Typical sizes:

| Pack | Typical summary size | Fits in context? |
|------|---------------------|------------------|
| Connectivity | 2-3 KB | Easily |
| DNS | 3-5 KB | Easily |
| HTTPS | 4-6 KB | Easily |
| Streaming | 5-8 KB | Easily |
| Security | 4-7 KB | Easily |
| Custom (all queries) | 8-15 KB | Yes |

If a section would exceed its allocation (e.g., 200+ unique DNS domains), truncate to top-N entries and add a `"truncated": true, "total_count": 247` annotation. The AI must be told about truncation so it doesn't assume the list is complete.

---

## 4. Stage 2: Interest Detection

Before AI sees anything, deterministic rules flag what's noteworthy. This serves two purposes: (a) the stats dashboard can highlight anomalies without AI, and (b) the AI prompt includes pre-identified focus areas so it doesn't waste tokens re-scanning for obvious issues.

### 4.1 InterestAnnotations Schema

```python
class AnomalyFlag(BaseModel):
    field: str             # JSON path: "tcp_health.retransmission_rate_pct"
    value: float | int | str
    threshold: float | int | str
    severity: str          # "info", "warning", "critical"
    label: str             # human-readable: "TCP retransmission rate exceeds 1%"

class InterestWindow(BaseModel):
    """A time window within the capture that is unusually interesting."""
    start_sec: int
    end_sec: int
    reason: str            # "throughput_drop", "retx_burst", "dns_failure_cluster"
    details: str           # "Throughput dropped from 8.2 to 0.4 Mbps at second 34"

class FocusFlow(BaseModel):
    """A specific conversation the AI should examine closely."""
    src: str
    dst: str
    reason: str            # "highest_retransmissions", "anomalous_port", "largest_flow"

class InterestAnnotations(BaseModel):
    anomaly_flags: list[AnomalyFlag]
    interesting_windows: list[InterestWindow]
    focus_flows: list[FocusFlow]
    overall_health: str    # "healthy", "degraded", "unhealthy"
    pack_specific_notes: list[str]  # free-form notes from pack-specific rules
```

### 4.2 Pack-Specific Threshold Rules

#### Connectivity Pack Thresholds

| Field | Warning | Critical | Label |
|-------|---------|----------|-------|
| `icmp.loss_rate_pct` | >5% | >20% | Packet loss to gateway |
| `dns.queries_over_1000ms` | >0 | >5 | DNS resolution failures |
| `dns.nxdomain_count` | >5 | >20 | Excessive NXDOMAIN responses |
| `tcp_health.retransmission_rate_pct` | >2% | >10% | TCP delivery problems |
| `tcp_health.rst_count` | >10 | >50 | Connection rejections |
| `icmp.unreachable_count` | >0 | >5 | Network unreachable messages |

#### DNS Pack Thresholds

| Field | Warning | Critical | Label |
|-------|---------|----------|-------|
| `dns.avg_response_time_ms` | >100 | >500 | Slow DNS resolution |
| `dns.p95_response_time_ms` | >300 | >1000 | DNS tail latency |
| `dns.nxdomain_count / dns.total_queries` | >10% | >30% | High NXDOMAIN ratio |
| `dns.servfail_count` | >0 | >5 | DNS server errors |
| `dns.refused_count` | >0 | >3 | DNS queries refused |
| `len(dns.resolver_ips) > 1 unexpected` | any | — | Queries to non-configured resolvers |

#### HTTPS Pack Thresholds

| Field | Warning | Critical | Label |
|-------|---------|----------|-------|
| `tcp_health.retransmission_rate_pct` | >1% | >5% | TCP delivery issues affecting web |
| `tcp_health.zero_window_count` | >5 | >20 | Receiver buffer exhaustion |
| `tcp_health.rst_count / tcp_health.connection_attempts` | >10% | >30% | Connection failure rate |
| Conversation with >5% retransmissions | per-flow | per-flow | Degraded flow |
| `throughput.std_dev_bps / throughput.avg_bps` | >0.8 | >1.5 | Unstable throughput |

#### Streaming Pack Thresholds

| Field | Warning | Critical | Label |
|-------|---------|----------|-------|
| `tcp_health.retransmission_rate_pct` | >0.5% | >2% | Retransmissions affecting stream (tighter threshold) |
| `throughput.min_bps` | <2 Mbps | <500 Kbps | Throughput dip below SD ABR rung |
| `throughput` consecutive intervals <2 Mbps | >3s | >8s | Sustained throughput stall (probable rebuffer) |
| `throughput.std_dev_bps / throughput.avg_bps` | >0.5 | >1.0 | Throughput instability |
| `dns.top_queried_domains` CDN patterns | info | — | CDN domain detected (context for AI) |
| Largest flow >80% of total bytes | info | — | Dominant media flow identified |

#### Security Pack Thresholds

| Field | Warning | Critical | Label |
|-------|---------|----------|-------|
| Non-RFC1918 src IP on LAN | — | any | Spoofed source IP on local network |
| `dns.resolver_ips` not in expected set | any | — | DNS queries to unexpected resolver |
| >20 unique dst ports from single src | any | — | Possible port scan |
| >50 unique dst IPs from single src | any | — | Possible network scan |
| Endpoint on known-bad port (e.g., 4444, 31337) | any | — | Suspicious service port |
| DNS queries with >100 char subdomain | any | — | Possible DNS exfiltration |

### 4.3 Interesting Window Detection

Analyze the `throughput.intervals` array to find time windows worth noting:

```python
def detect_interesting_windows(summary: CaptureSummary) -> list[InterestWindow]:
    windows = []
    if not summary.throughput:
        return windows

    intervals = summary.throughput.intervals
    avg = summary.throughput.avg_bps

    # Detect throughput drops >60% below average sustained for 3+ seconds
    drop_start = None
    for iv in intervals:
        if iv.bytes * 8 < avg * 0.4:
            if drop_start is None:
                drop_start = iv.second
        else:
            if drop_start is not None and iv.second - drop_start >= 3:
                windows.append(InterestWindow(
                    start_sec=drop_start,
                    end_sec=iv.second,
                    reason="throughput_drop",
                    details=f"Throughput dropped >60% below average for "
                            f"{iv.second - drop_start}s starting at second {drop_start}",
                ))
            drop_start = None

    # Detect retransmission bursts (would need per-interval expert info — future enhancement)

    return windows
```

### 4.4 Overall Health Classification

```python
def classify_health(flags: list[AnomalyFlag]) -> str:
    if any(f.severity == "critical" for f in flags):
        return "unhealthy"
    if any(f.severity == "warning" for f in flags):
        return "degraded"
    return "healthy"
```

This classification appears as a badge in the UI (green/yellow/red) before the user ever requests AI.

---

## 5. Stage 3: AI Interpretation

### 5.1 AI Input Schema

The AI receives a single JSON document constructed from the CaptureSummary + InterestAnnotations. The schema is the same for all providers.

```json
{
  "analysis_pack": "streaming",
  "pack_description": "Traffic captured to diagnose video streaming quality issues.",
  "capture_context": {
    "interface": "wlan0",
    "bpf_filter": "tcp port 80 or tcp port 443 or udp portrange 1024-65535",
    "duration_secs": 58.3,
    "total_packets": 24531,
    "total_bytes": 18420156
  },
  "pre_identified_issues": [
    {
      "field": "tcp_health.retransmission_rate_pct",
      "value": 1.41,
      "threshold": 0.5,
      "severity": "warning",
      "label": "TCP retransmission rate exceeds 0.5% streaming threshold"
    },
    {
      "field": "throughput.intervals[34:38]",
      "value": "avg 0.4 Mbps",
      "threshold": "2 Mbps",
      "severity": "critical",
      "label": "Sustained throughput stall at seconds 34-38"
    }
  ],
  "focus_flows": [
    {
      "src": "192.168.4.10",
      "dst": "104.16.132.229:443",
      "reason": "largest_flow, highest_retransmissions"
    }
  ],
  "overall_health": "degraded",
  "summary_data": {
    "protocols": [ ... ],
    "tcp_health": { ... },
    "conversations": [ ... ],
    "dns": { ... },
    "throughput": { ... },
    "expert_alerts": { ... }
  },
  "truncations": [
    {"section": "conversations", "shown": 20, "total": 47}
  ]
}
```

**Key properties of this input:**

- **`pre_identified_issues`**: Tells the AI what deterministic analysis already found. The AI should confirm, contextualize, or dispute these — not ignore them.
- **`focus_flows`**: Tells the AI which conversations deserve deeper commentary.
- **`truncations`**: Tells the AI which sections were trimmed, preventing it from assuming the data is complete.
- **`summary_data`**: The actual statistics. This is the only source of truth the AI may cite.

### 5.2 AI Output Schema (AnalysisResult v2)

```python
class Confidence(str, Enum):
    HIGH = "HIGH"       # multiple corroborating data points, clear threshold violation
    MEDIUM = "MEDIUM"   # single strong indicator OR multiple weak indicators
    LOW = "LOW"         # pattern suggestive but data insufficient for certainty

class EvidenceCitation(BaseModel):
    field: str          # JSON path: "tcp_health.retransmission_rate_pct"
    value: str          # "1.41%"
    interpretation: str # "312 retransmissions out of 22,100 TCP packets"

class Finding(BaseModel):
    id: str                          # "F1", "F2", etc. — stable reference
    title: str                       # one-line: "TCP retransmission rate degrades streaming quality"
    severity: str                    # "critical", "high", "medium", "low", "info"
    confidence: Confidence
    category: str                    # "retransmissions", "throughput", "dns", "tls", "security", "protocol"
    description: str                 # 2-4 sentence explanation
    evidence: list[EvidenceCitation] # MUST have at least one
    affected_flows: list[str]        # ["192.168.4.10:54321 -> 104.16.132.229:443"]
    likely_causes: list[str]         # ["WiFi interference", "Congested uplink"]
    next_steps: list[str]            # ["Check WiFi signal strength", "Run connectivity pack"]
    cross_references: list[str]      # ["F2"] — findings that relate to this one

class InsufficientEvidenceNote(BaseModel):
    """Areas the AI wanted to investigate but couldn't due to data limitations."""
    area: str                        # "RTT measurement"
    reason: str                      # "No TCP timestamp options captured; RTT cannot be derived"
    what_would_help: str             # "Capture with full TCP options or run a connectivity pack"

class AnalysisResultV2(BaseModel):
    capture_id: str
    analysis_pack: str
    executive_summary: str           # 2-4 sentences, non-technical
    health_verdict: str              # "healthy", "degraded", "unhealthy"
    findings: list[Finding]          # ordered by severity descending
    insufficient_evidence: list[InsufficientEvidenceNote]
    comparative_notes: str | None    # only if comparing two captures
    metadata: AnalysisMetadata

class AnalysisMetadata(BaseModel):
    provider: str                    # "anthropic" or "openai"
    model: str
    input_tokens: int
    output_tokens: int
    analysis_duration_ms: int
    analyzed_at: str                 # ISO 8601
    framework_version: str           # "2.0" — for schema evolution
```

### 5.3 Response Validation

After parsing the AI response, apply these post-processing checks:

```python
def validate_analysis(result: AnalysisResultV2, summary: CaptureSummary) -> AnalysisResultV2:
    """Strip or flag findings that violate guardrails."""
    valid_findings = []
    for finding in result.findings:
        # Rule 1: Every finding must cite at least one evidence field
        if not finding.evidence:
            logger.warning("Dropping finding %s: no evidence citations", finding.id)
            continue

        # Rule 2: Every cited field must exist in the input summary
        valid_evidence = []
        for cite in finding.evidence:
            if _field_exists_in_summary(cite.field, summary):
                valid_evidence.append(cite)
            else:
                logger.warning("Dropping citation for non-existent field: %s", cite.field)
        if not valid_evidence:
            logger.warning("Dropping finding %s: all citations invalid", finding.id)
            continue
        finding.evidence = valid_evidence

        # Rule 3: Cited values must approximately match actual values
        for cite in finding.evidence:
            actual = _get_field_value(cite.field, summary)
            if actual is not None and not _values_close_enough(cite.value, actual):
                logger.warning(
                    "Finding %s cites %s=%s but actual=%s — correcting",
                    finding.id, cite.field, cite.value, actual,
                )
                cite.value = str(actual)

        valid_findings.append(finding)

    result.findings = valid_findings
    return result
```

---

## 6. Analysis Pack Personas and Prompt Templates

Each pack gets a dedicated system prompt and user prompt template. The system prompt establishes the persona and rules. The user prompt injects the data.

### 6.1 Shared System Prompt (all packs)

```
You are a network diagnostician embedded in WiFry, a WiFi test appliance running on Raspberry Pi.
You receive structured statistics extracted from a packet capture — never raw pcap data.

RULES — these are absolute constraints on your output:

1. EVIDENCE REQUIRED: Every finding MUST cite at least one field from summary_data
   with its exact value. Do not round, estimate, or fabricate numbers.

2. CONFIDENCE LEVELS: Use exactly these definitions:
   - HIGH: Multiple corroborating data points clearly confirm the issue.
     Example: retransmission_rate_pct=3.2% AND throughput drops AND expert alerts all point to
     the same TCP delivery problem.
   - MEDIUM: One strong indicator or multiple weak indicators suggest the issue.
     Example: retransmission_rate_pct=1.5% is above threshold but no corroborating throughput impact.
   - LOW: Pattern is suggestive but data is insufficient for certainty.
     Example: a few RST packets could indicate connection problems or normal connection teardown.

3. INSUFFICIENT EVIDENCE: If the capture data cannot answer a question, say so explicitly
   in the insufficient_evidence array. Do NOT speculate to fill gaps. Do NOT infer data
   that isn't present (e.g., don't claim "RTT is high" if no RTT data exists).

4. CAUSATION vs CORRELATION: Use "likely caused by" or "consistent with" — never
   "caused by" unless the evidence is unambiguous (e.g., 100% ICMP unreachable = destination down).

5. SCOPE: Only analyze what the capture data shows. Do not speculate about:
   - Server-side issues (you can only see the client-side conversation)
   - Application-layer behavior above what protocol dissection reveals
   - WiFi PHY-layer details (you see IP and above, not RF)
   The capture sees traffic at the WiFi AP. You see what crosses the AP interface.

6. TRUNCATION: If the input includes a "truncations" array, acknowledge that your view
   is partial. Do not claim "only N conversations exist" when the data was truncated.

7. FORMAT: Respond with valid JSON matching the AnalysisResultV2 schema.
   Do not wrap in markdown code blocks. Do not include commentary outside the JSON.
```

### 6.2 Connectivity Pack Prompt

```
## Analysis Pack: Connectivity Check

This capture was taken to determine basic network health: can traffic reach the
internet, is DNS working, and are there fundamental delivery problems?

PAY ATTENTION TO:
- ICMP echo/reply: Calculate packet loss. Any loss to the default gateway is significant.
- DNS resolution: Are queries completing? What are response times? Any NXDOMAIN or SERVFAIL?
- TCP connection setup: Are SYN packets getting SYN-ACK responses? High RST count?
- Retransmissions: Rate above 2% is concerning for basic connectivity.
- Unreachable messages: ICMP unreachable indicates routing or firewall problems.

COMMON DIAGNOSES for this pack:
- "No internet": ICMP loss to gateway + DNS failures → gateway/upstream problem
- "Slow browsing": DNS resolution >200ms → DNS server or path problem
- "Intermittent drops": Periodic retransmission bursts → WiFi interference or congestion
- "Can ping but can't browse": ICMP works, TCP RST on port 443 → firewall or proxy issue

STREAMING-SPECIFIC: Not applicable for this pack. Focus on fundamental reachability.

## Pre-Identified Issues
{pre_identified_issues_json}

## Focus Flows
{focus_flows_json}

## Capture Statistics
{summary_data_json}

## Data Truncations
{truncations_json}
```

### 6.3 DNS Pack Prompt

```
## Analysis Pack: DNS Troubleshooting

This capture focused exclusively on DNS traffic (UDP/TCP port 53) to diagnose
name resolution problems.

PAY ATTENTION TO:
- Response time distribution: avg, median, and P95. P95 >300ms is poor.
- NXDOMAIN ratio: >10% of queries returning NXDOMAIN may indicate misconfigured services
  or malware generating random subdomains (DGA).
- SERVFAIL and REFUSED: Any count >0 indicates server-side DNS problems.
- Resolver IPs: Are queries going to expected resolvers? Queries to unexpected IPs
  could indicate DNS hijacking or misconfigured clients.
- Query type breakdown: Unusual volume of TXT, MX, or ANY queries from a client device
  may indicate DNS tunneling or exfiltration.
- Slow domains: Which specific domains have the worst resolution times?

COMMON DIAGNOSES for this pack:
- "Slow page loads, fast once loaded": High DNS P95 → resolver latency or upstream DNS issue
- "Some sites work, some don't": NXDOMAIN for specific domains → DNS filtering or propagation
- "DNS works but intermittently slow": Bimodal response times → primary/fallback resolver split
- "Unexpected resolver": Queries to 1.1.1.1 when configured for 8.8.8.8 → hardcoded DNS in app

IMPORTANT: DNS tunneling and exfiltration are serious findings. Only flag them at MEDIUM
confidence minimum, and require: (a) queries to a single unusual domain with (b) encoded-looking
subdomains (long random strings) and (c) high query volume. One long subdomain is not enough.

## Pre-Identified Issues
{pre_identified_issues_json}

## Focus Flows
{focus_flows_json}

## Capture Statistics
{summary_data_json}

## Data Truncations
{truncations_json}
```

### 6.4 HTTPS/Web Pack Prompt

```
## Analysis Pack: HTTPS / Web Troubleshooting

This capture focused on HTTP/HTTPS traffic (ports 80, 443, 8080) to diagnose
web browsing and API performance issues.

PAY ATTENTION TO:
- TCP retransmission rate: >1% is poor for web. Causes slow page loads and timeouts.
- Per-conversation retransmissions: Identify which specific flows are degraded.
  A single flow with 10% retransmissions among healthy flows points to a server-side
  or path-specific problem, not a local WiFi issue.
- Zero windows: Indicate the receiver (client device) can't consume data fast enough.
  Common on memory-constrained devices.
- RST ratio: connection_resets / connection_attempts. >10% is abnormal.
- Throughput stability: High variance means inconsistent user experience.
- TLS versions: TLSv1.0/1.1 connections are deprecated and may indicate
  outdated clients or servers.
- TLS SNI patterns: Identify which services the device is connecting to.

COMMON DIAGNOSES for this pack:
- "Slow page loads": High retransmission rate on large flows → WiFi/path congestion
- "Timeout errors": SYN packets without SYN-ACK → destination unreachable or firewall
- "Mixed fast/slow": Some conversations healthy, some degraded → server-specific issue
- "Connection resets": High RST count → server rejecting connections or load balancer issue

## Pre-Identified Issues
{pre_identified_issues_json}

## Focus Flows
{focus_flows_json}

## Capture Statistics
{summary_data_json}

## Data Truncations
{truncations_json}
```

### 6.5 Streaming/Video Pack Prompt

```
## Analysis Pack: Streaming / Video Debug

This capture targeted video streaming traffic to diagnose buffering, quality drops,
and playback interruptions.

PAY ATTENTION TO:
- Throughput timeline: This is the most important data for streaming. Look for:
  - Sustained dips below 2 Mbps (SD quality floor)
  - Sustained dips below 5 Mbps (HD quality floor)
  - Sustained dips below 15 Mbps (4K quality floor)
  - Dips lasting >3 seconds likely cause visible rebuffering events
  - The interesting_windows in pre_identified_issues already flag these
- Retransmission rate: Even 0.5% can cause playback stalls because streaming clients
  have tight buffering deadlines. This is a TIGHTER threshold than general web traffic.
- Dominant flow identification: The largest flow by bytes is almost certainly the media
  stream. Examine its retransmission count specifically.
- CDN patterns in DNS: Look for domains matching known CDN patterns
  (akamai, cloudfront, fastly, edgecast, cdn.*, manifest.*, segment.*).
  Multiple CDN domains may indicate ABR switching or multi-CDN configuration.
- UDP traffic: Could be QUIC (HTTP/3) or RTP. Large UDP flows to port 443 are likely QUIC.
  UDP packet loss manifests differently — look for gaps in packet counts.
- Throughput asymmetry: If A→B bytes >> B→A bytes in the media flow, the stream is
  downloading (expected). If roughly symmetric, it might be a video call (different diagnosis).

COMMON DIAGNOSES for this pack:
- "Buffering every few seconds": Periodic throughput dips below ABR floor + retransmissions
  → WiFi congestion or upstream bandwidth limitation
- "Starts HD then drops to SD": Throughput decreasing over time → competing traffic or
  thermal throttling on WiFi
- "Works fine then suddenly freezes": Throughput cliff (not gradual) → WiFi disassociation
  or upstream outage
- "Audio fine but video freezes": Retransmissions on the large flow only → the media
  segments are being retransmitted, audio segments are small enough to survive

IMPORTANT: You cannot determine ABR bitrate ladder decisions from packet capture alone.
You can observe throughput available to the client and flag when it drops below common
quality thresholds. Say "throughput fell below the typical HD threshold" not "the player
downshifted to SD."

## Pre-Identified Issues
{pre_identified_issues_json}

## Focus Flows
{focus_flows_json}

## Capture Statistics
{summary_data_json}

## Data Truncations
{truncations_json}
```

### 6.6 Security/Anomaly Pack Prompt

```
## Analysis Pack: Security / Anomaly Scan

This capture recorded ALL traffic (no BPF filter) to look for unexpected,
suspicious, or anomalous network behavior.

PAY ATTENTION TO:
- Unexpected endpoints: Devices on the LAN (192.168.4.x) connecting to unusual
  destination IPs or ports. Compare against what a typical consumer device does
  (DNS, HTTPS on 443, maybe QUIC on 443).
- DNS anomalies:
  - Queries to resolvers other than the configured ones (192.168.4.1 / 8.8.8.8)
  - Very long subdomain labels (>50 chars) — possible DNS tunneling
  - High volume of TXT queries — possible DNS exfiltration
  - Queries to recently-registered or suspicious TLDs
- Port scanning patterns: A single source connecting to many destination ports
  in rapid succession.
- Network scanning patterns: A single source connecting to many destination IPs.
- Broadcast/multicast volume: High broadcast traffic can indicate a misconfigured
  device or broadcast storm.
- Non-RFC1918 source IPs on the LAN: Should not exist. Indicates spoofing.
- Suspicious service ports: 4444 (Metasploit default), 31337, 1337, 6667 (IRC),
  6697 (IRC+TLS). These are only suspicious in combination with other indicators.

IMPORTANT: Security findings carry more weight than other packs. Apply these rules:
- Do NOT flag normal HTTPS traffic to major services as suspicious
- Do NOT flag standard NTP, mDNS, SSDP, or DHCP traffic as anomalous
- DO flag unexpected plaintext protocols (HTTP on non-standard ports, telnet, FTP)
- CONFIDENCE must be MEDIUM or higher for any security finding. LOW confidence
  security findings should go in insufficient_evidence instead, framed as
  "worth investigating" rather than "detected threat."
- Always distinguish between "unusual" (LOW) and "malicious" (needs HIGH evidence)

COMMON DIAGNOSES for this pack:
- "Smart TV phoning home": Many connections to tracking/analytics domains → expected
  but notable for privacy audit
- "IoT device scanning": Single device connecting to many LAN IPs → possibly
  compromised or misconfigured
- "DNS exfiltration": High-entropy subdomain queries to single domain → investigate
- "Rogue DHCP": DHCP offers from unexpected IP → network infrastructure problem

## Pre-Identified Issues
{pre_identified_issues_json}

## Focus Flows
{focus_flows_json}

## Capture Statistics
{summary_data_json}

## Data Truncations
{truncations_json}
```

---

## 7. "Insufficient Evidence" Rules

The AI must produce an `InsufficientEvidenceNote` (not a finding) when:

| Condition | Insufficient evidence area | What would help |
|---|---|---|
| No ICMP data in capture | Packet loss measurement | Run connectivity pack (captures ICMP) |
| No TCP timestamp options | RTT estimation | Capture with full TCP options; some implementations strip them |
| BPF filter excluded DNS | DNS health assessment | Run DNS pack or custom capture including port 53 |
| Capture duration <10s | Throughput stability | Longer capture (30s+ for meaningful variance) |
| <100 TCP packets total | Retransmission rate reliability | Statistical sample too small; rate may not be representative |
| No throughput intervals (0 bytes) | Throughput analysis | No data traffic captured; check BPF filter or verify device is active |
| All conversations truncated | Complete traffic picture | Data was truncated to top 20 flows; {total} flows existed |
| No expert alerts (tshark query failed) | TCP health deep-dive | Expert info extraction may have timed out on large capture |
| Single DNS resolver only | Resolver comparison | Only one resolver observed; cannot assess primary vs fallback behavior |

### Rules for the AI

The system prompt includes this directive:

```
You MUST add an InsufficientEvidenceNote when:
- A field you would normally analyze is null or missing from summary_data
- A section has "truncated": true and your conclusion depends on the full dataset
- The capture duration is <15 seconds and you're asked about patterns or stability
- The total packet count for the relevant protocol is <100
- You want to make a claim about something outside the capture's BPF scope

You MUST NOT:
- Present a LOW confidence finding as if it were established fact
- Fill gaps with assumptions about "typical" network behavior
- Claim a problem doesn't exist just because you don't see evidence of it
  (absence of evidence is not evidence of absence — say "not observed" not "not present")
```

---

## 8. Narrowing: Focus on Interesting Windows and Flows

### 8.1 Problem

A 120-second streaming capture generates ~120 throughput intervals and ~50 conversations. Most of these are uninteresting (steady throughput, healthy connections). Sending all of it to the AI wastes tokens and dilutes attention.

### 8.2 Strategy: Pre-Filter Before AI

The interest detection stage (Stage 2) already identifies anomalous windows and focus flows. The AI input assembler uses these to construct a focused view:

```python
def build_ai_input(summary: CaptureSummary) -> dict:
    """Construct the AI input document with focused data."""
    data = summary.model_dump()
    interest = summary.interest

    # Throughput: include only interesting windows + 5s of context on each side
    if summary.throughput and interest and interest.interesting_windows:
        all_intervals = summary.throughput.intervals
        keep_seconds = set()
        for w in interest.interesting_windows:
            for s in range(max(0, w.start_sec - 5), w.end_sec + 6):
                keep_seconds.add(s)
        # Always include first 5s and last 5s for baseline
        for s in range(min(5, len(all_intervals))):
            keep_seconds.add(s)
        for s in range(max(0, len(all_intervals) - 5), len(all_intervals)):
            keep_seconds.add(s)

        data["summary_data"]["throughput"]["intervals"] = [
            iv for iv in all_intervals if iv["second"] in keep_seconds
        ]
        data["truncations"].append({
            "section": "throughput.intervals",
            "shown": len(keep_seconds),
            "total": len(all_intervals),
            "note": "Only interesting windows + context included. "
                    "Full average/peak/min stats reflect complete capture.",
        })

    # Conversations: top 10 by bytes + any flagged focus flows
    if summary.conversations:
        top_10 = sorted(
            summary.conversations,
            key=lambda c: c.bytes_a_to_b + c.bytes_b_to_a,
            reverse=True,
        )[:10]
        focus_ips = {(f.src, f.dst) for f in (interest.focus_flows if interest else [])}
        extras = [
            c for c in summary.conversations
            if (c.src, f"{c.dst}:{c.dst_port}") in focus_ips
            and c not in top_10
        ]
        data["summary_data"]["conversations"] = [
            c.model_dump() for c in top_10 + extras
        ]

    # DNS: top 10 queried + all slow + all failing
    if summary.dns:
        data["summary_data"]["dns"]["top_queried_domains"] = (
            summary.dns.top_queried_domains[:10]
        )
        # top_slow_domains already filtered by extraction

    return data
```

### 8.3 Per-Interval Detail vs Aggregates

The AI always receives the full-capture aggregate statistics (`avg_bps`, `peak_bps`, `retransmission_rate_pct`, etc.). Per-interval detail is only included for interesting windows. This means:

- AI can accurately characterize the overall capture ("average throughput was 5.2 Mbps")
- AI can describe specific anomalies ("throughput dropped to 0.3 Mbps between seconds 34-38")
- AI cannot fabricate per-second data for windows not included

---

## 9. Comparative Analysis: Two-Capture Diff

### 9.1 When to Compare

Comparison is triggered when the user selects two completed captures and clicks "Compare." Common scenarios:

- Before/after applying a network impairment
- Same test on different network profiles
- Same streaming test at different times of day

### 9.2 Comparison Input Schema

```python
class CaptureComparison(BaseModel):
    baseline: CaptureSummary           # typically "before" or "healthy" capture
    subject: CaptureSummary            # typically "after" or "degraded" capture
    baseline_label: str                # "Before impairment" or custom label
    subject_label: str                 # "During 3G Congested" or custom label
    deltas: ComparisonDeltas           # pre-computed numeric diffs

class ComparisonDeltas(BaseModel):
    """Pre-computed differences between baseline and subject."""
    duration_diff_secs: float
    packet_count_diff: int
    total_bytes_diff: int

    # TCP health deltas (subject - baseline; positive = worse if metric is "bad")
    retransmission_rate_delta: float | None   # +2.1 means subject is 2.1% higher
    duplicate_ack_delta: int | None
    zero_window_delta: int | None
    rst_count_delta: int | None

    # Throughput deltas
    avg_bps_delta: float | None               # negative = subject slower
    peak_bps_delta: float | None
    stability_delta: float | None             # change in coefficient of variation

    # DNS deltas
    avg_dns_time_delta_ms: float | None       # positive = subject slower
    nxdomain_delta: int | None
    failure_delta: int | None

    # Derived flags
    degraded_metrics: list[str]               # ["retransmission_rate", "avg_throughput"]
    improved_metrics: list[str]               # ["dns_response_time"]
    unchanged_metrics: list[str]
```

### 9.3 Comparison Prompt Template

```
## Comparative Analysis

You are comparing two packet captures to explain what changed between them.

BASELINE: "{baseline_label}"
- Duration: {baseline.meta.duration_secs}s, {baseline.meta.total_packets} packets
- Captured: {baseline.meta.started_at}

SUBJECT: "{subject_label}"
- Duration: {subject.meta.duration_secs}s, {subject.meta.total_packets} packets
- Captured: {subject.meta.started_at}

## Pre-Computed Deltas
{deltas_json}

## Baseline Capture Statistics
{baseline_summary_json}

## Subject Capture Statistics
{subject_summary_json}

YOUR TASK:
1. Explain what changed between the two captures in plain language.
2. For each degraded metric, explain the magnitude and likely impact.
3. If the captures used different analysis packs or BPF filters, note that
   direct comparison may be misleading and explain why.
4. If capture durations differ by >50%, note that per-unit metrics (rates,
   averages) are more reliable than absolute counts for comparison.
5. Produce findings using the same schema as single-capture analysis.
   Each finding should reference metrics from BOTH captures where applicable.
   Use evidence citations like "baseline.tcp_health.retransmission_rate_pct"
   and "subject.tcp_health.retransmission_rate_pct".
```

### 9.4 Delta Computation Rules

Deltas are computed deterministically before AI sees the data:

```python
def compute_deltas(baseline: CaptureSummary, subject: CaptureSummary) -> ComparisonDeltas:
    degraded, improved, unchanged = [], [], []

    # Retransmission rate: higher is worse
    if baseline.tcp_health and subject.tcp_health:
        delta = subject.tcp_health.retransmission_rate_pct - baseline.tcp_health.retransmission_rate_pct
        if delta > 0.5:
            degraded.append("retransmission_rate")
        elif delta < -0.5:
            improved.append("retransmission_rate")
        else:
            unchanged.append("retransmission_rate")

    # Throughput: lower is worse
    if baseline.throughput and subject.throughput:
        delta = subject.throughput.avg_bps - baseline.throughput.avg_bps
        if delta < -baseline.throughput.avg_bps * 0.1:  # >10% drop
            degraded.append("avg_throughput")
        elif delta > baseline.throughput.avg_bps * 0.1:
            improved.append("avg_throughput")
        else:
            unchanged.append("avg_throughput")

    # DNS response time: higher is worse
    if baseline.dns and subject.dns:
        if baseline.dns.avg_response_time_ms and subject.dns.avg_response_time_ms:
            delta = subject.dns.avg_response_time_ms - baseline.dns.avg_response_time_ms
            if delta > 50:
                degraded.append("dns_response_time")
            elif delta < -50:
                improved.append("dns_response_time")
            else:
                unchanged.append("dns_response_time")

    return ComparisonDeltas(
        degraded_metrics=degraded,
        improved_metrics=improved,
        unchanged_metrics=unchanged,
        # ... fill other fields similarly
    )
```

---

## 10. Guardrails

### 10.1 Input Guardrails (before AI call)

| Guardrail | Implementation | Why |
|---|---|---|
| Summary size cap | Reject if `len(json.dumps(summary)) > 20_000` | Prevent unbounded token cost |
| Empty capture rejection | Don't call AI if `total_packets < 10` | Nothing to analyze |
| Rate limit | Max 1 AI call per 30 seconds per capture | Prevent spam-clicking "Analyze" |
| Provider key check | Return helpful error if no API key configured | Don't waste a call that will 401 |
| Pack validation | Verify `analysis_pack` is a known pack | Prevent prompt injection via pack name |

### 10.2 Output Guardrails (after AI response)

| Guardrail | Implementation | Why |
|---|---|---|
| Evidence validation | Drop findings with no evidence citations | Rule 1: every claim needs proof |
| Field existence check | Drop citations referencing fields not in the input | Prevent hallucinated data |
| Value accuracy check | Correct cited values that don't match input data | Prevent confidently wrong numbers |
| Severity cap | Findings with LOW confidence cannot be "critical" | Prevent alarm fatigue |
| Finding count cap | Max 10 findings per analysis | Focus on what matters |
| Confidence override | If cited field value is null, force confidence to LOW | Can't be confident about missing data |
| Schema validation | Validate JSON against Pydantic model; fallback to raw summary on failure | Graceful degradation |
| IP/hostname scrubbing | Don't expose LAN topology in executive_summary (keep in findings only) | Summary may be shared; detail stays in findings |

### 10.3 Prompt Injection Defense

The input to the AI is entirely machine-generated from deterministic tshark output. There is no user-supplied free text in the data payload. However:

- Domain names in DNS queries could theoretically contain adversarial text. The DNS extraction pipeline sanitizes domain names: strip non-printable characters, truncate to 253 chars, reject domains containing prompt-like patterns (`ignore previous`, `system:`, `<|`, etc.).
- Conversation IP addresses are validated as valid IP addresses before inclusion.
- The system prompt is hardcoded per pack, not user-configurable.

### 10.4 Cost Control

| Control | Value | Rationale |
|---|---|---|
| Max input tokens (estimated) | ~5,000 | 20 KB JSON / ~4 chars per token |
| Max output tokens | 4,096 | Enough for 10 findings with full evidence |
| Rate limit | 1 call / 30s / capture | Prevent rapid re-analyze |
| Model selection | Claude Sonnet (not Opus) / GPT-4o-mini | Cost-effective for structured analysis |
| Caching | Analysis saved to disk; re-analyze requires explicit user action | Don't re-analyze on page reload |
| Batch comparison | Compare uses one AI call with both summaries, not two calls | Half the cost |

Estimated cost per analysis: **$0.01-0.03** (5K input tokens + 2K output tokens at Sonnet/4o-mini rates).

---

## 11. Example: Full Streaming Analysis Walkthrough

### Input: CaptureSummary (abbreviated)

```json
{
  "meta": {
    "capture_id": "cap_streaming_01",
    "analysis_pack": "streaming",
    "duration_secs": 62.1,
    "total_packets": 31204,
    "total_bytes": 24100000
  },
  "tcp_health": {
    "retransmission_count": 187,
    "retransmission_rate_pct": 0.71,
    "duplicate_ack_count": 43,
    "zero_window_count": 0,
    "rst_count": 2,
    "syn_count": 14,
    "fin_count": 12,
    "connection_attempts": 14,
    "connection_completions": 14
  },
  "conversations": [
    {
      "src": "192.168.4.10", "src_port": 0,
      "dst": "13.249.131.42", "dst_port": 443,
      "protocol": "TCP",
      "packets_a_to_b": 2100, "packets_b_to_a": 22800,
      "bytes_a_to_b": 210000, "bytes_b_to_a": 21500000,
      "duration_secs": 60.2,
      "retransmissions": 172
    },
    {
      "src": "192.168.4.10", "src_port": 0,
      "dst": "8.8.8.8", "dst_port": 53,
      "protocol": "UDP",
      "packets_a_to_b": 24, "packets_b_to_a": 24,
      "bytes_a_to_b": 1800, "bytes_b_to_a": 4200,
      "duration_secs": 58.0,
      "retransmissions": null
    }
  ],
  "dns": {
    "total_queries": 24,
    "unique_domains": 8,
    "nxdomain_count": 0,
    "servfail_count": 0,
    "avg_response_time_ms": 18.4,
    "top_queried_domains": [
      {"domain": "d2zihajmogu5jn.cloudfront.net", "count": 6, "avg_time_ms": 15.2},
      {"domain": "manifest.prod.boltdns.net", "count": 4, "avg_time_ms": 22.1}
    ]
  },
  "throughput": {
    "avg_bps": 3104000,
    "peak_bps": 12800000,
    "min_bps": 180000,
    "std_dev_bps": 2900000,
    "intervals": [
      {"second": 0, "bytes": 45000, "packets": 120},
      {"second": 1, "bytes": 890000, "packets": 580},
      {"second": 2, "bytes": 1200000, "packets": 790},
      "... (62 entries total, only interesting windows sent to AI)"
    ]
  },
  "interest": {
    "anomaly_flags": [
      {
        "field": "throughput.std_dev_bps / throughput.avg_bps",
        "value": 0.93,
        "threshold": 0.5,
        "severity": "warning",
        "label": "Throughput instability: coefficient of variation 0.93 exceeds 0.5 threshold"
      }
    ],
    "interesting_windows": [
      {
        "start_sec": 22,
        "end_sec": 28,
        "reason": "throughput_drop",
        "details": "Throughput dropped from 5.1 Mbps to 0.18 Mbps for 6 seconds"
      },
      {
        "start_sec": 45,
        "end_sec": 49,
        "reason": "throughput_drop",
        "details": "Throughput dropped from 4.8 Mbps to 0.22 Mbps for 4 seconds"
      }
    ],
    "focus_flows": [
      {
        "src": "192.168.4.10",
        "dst": "13.249.131.42:443",
        "reason": "largest_flow, highest_retransmissions"
      }
    ],
    "overall_health": "degraded"
  }
}
```

### Expected AI Output (abbreviated)

```json
{
  "capture_id": "cap_streaming_01",
  "analysis_pack": "streaming",
  "executive_summary": "Video streaming over this WiFi connection shows periodic throughput stalls that likely cause visible buffering. Two throughput drops to near-zero were detected during the 62-second capture, each lasting 4-6 seconds. The dominant media flow to a CloudFront CDN has a retransmission rate of 0.69%, which is manageable but concentrated around the stall periods.",
  "health_verdict": "degraded",
  "findings": [
    {
      "id": "F1",
      "title": "Periodic throughput stalls likely causing rebuffering",
      "severity": "high",
      "confidence": "HIGH",
      "category": "throughput",
      "description": "Two distinct throughput drops were detected: seconds 22-28 (0.18 Mbps, 6s) and seconds 45-49 (0.22 Mbps, 4s). Both fell well below the 2 Mbps SD streaming floor. At ~25-second intervals, this pattern is consistent with periodic WiFi contention or upstream congestion cycling.",
      "evidence": [
        {"field": "throughput.min_bps", "value": "180000", "interpretation": "0.18 Mbps minimum throughput, far below any streaming quality threshold"},
        {"field": "interest.interesting_windows[0]", "value": "seconds 22-28", "interpretation": "6-second throughput drop to 0.18 Mbps"},
        {"field": "interest.interesting_windows[1]", "value": "seconds 45-49", "interpretation": "4-second throughput drop to 0.22 Mbps"},
        {"field": "throughput.std_dev_bps", "value": "2900000", "interpretation": "Coefficient of variation 0.93 — throughput is highly unstable"}
      ],
      "affected_flows": ["192.168.4.10 -> 13.249.131.42:443"],
      "likely_causes": [
        "WiFi channel contention from neighboring networks",
        "Upstream bandwidth saturation (competing traffic on the WAN link)",
        "WiFi power save mode causing periodic disconnects"
      ],
      "next_steps": [
        "Run a WiFi scan to check channel congestion",
        "Capture again with the connectivity pack to check for ICMP loss during stall windows",
        "Check if other devices share the upstream connection"
      ],
      "cross_references": ["F2"]
    },
    {
      "id": "F2",
      "title": "Media flow retransmissions concentrated in dominant CloudFront connection",
      "severity": "medium",
      "confidence": "MEDIUM",
      "category": "retransmissions",
      "description": "The primary media flow (192.168.4.10 -> 13.249.131.42:443) accounts for 172 of 187 total retransmissions (92%). The per-flow retransmission rate is 0.69% which is below the 2% critical threshold but above the 0.5% streaming warning threshold. These retransmissions are likely correlated with the throughput stalls in F1.",
      "evidence": [
        {"field": "conversations[0].retransmissions", "value": "172", "interpretation": "172 retransmissions on the dominant flow (22,800 server-to-client packets)"},
        {"field": "tcp_health.retransmission_rate_pct", "value": "0.71", "interpretation": "Overall 0.71% retransmission rate"},
        {"field": "conversations[0].bytes_b_to_a", "value": "21500000", "interpretation": "21.5 MB received — consistent with a ~3 Mbps video stream over 60 seconds"}
      ],
      "affected_flows": ["192.168.4.10 -> 13.249.131.42:443"],
      "likely_causes": [
        "WiFi packet loss during congestion windows",
        "Bufferbloat on upstream link causing delayed ACKs"
      ],
      "next_steps": [
        "Correlate retransmission timestamps with throughput dip windows (requires per-interval expert data)",
        "Apply the 'Connectivity' pack to measure baseline packet loss"
      ],
      "cross_references": ["F1"]
    },
    {
      "id": "F3",
      "title": "CloudFront CDN delivering media stream",
      "severity": "info",
      "confidence": "HIGH",
      "category": "dns",
      "description": "DNS queries to d2zihajmogu5jn.cloudfront.net and manifest.prod.boltdns.net identify this as a Brightcove/CloudFront video delivery. DNS resolution is healthy at 18.4ms average with no failures. The CDN selection is not the source of the streaming issues.",
      "evidence": [
        {"field": "dns.avg_response_time_ms", "value": "18.4", "interpretation": "DNS resolution averaging 18.4ms — well within normal range"},
        {"field": "dns.top_queried_domains[0].domain", "value": "d2zihajmogu5jn.cloudfront.net", "interpretation": "CloudFront CDN domain queried 6 times — media segment requests"},
        {"field": "dns.nxdomain_count", "value": "0", "interpretation": "No DNS lookup failures"}
      ],
      "affected_flows": [],
      "likely_causes": [],
      "next_steps": [],
      "cross_references": []
    }
  ],
  "insufficient_evidence": [
    {
      "area": "Per-interval retransmission correlation",
      "reason": "Expert info is aggregated across the full capture. Cannot confirm retransmissions coincide with throughput dips vs being spread evenly.",
      "what_would_help": "Per-second expert info extraction (future enhancement) or manual Wireshark inspection of the pcap during seconds 22-28 and 45-49."
    },
    {
      "area": "WiFi PHY-layer diagnostics",
      "reason": "Packet capture sees IP-layer and above. Cannot observe WiFi signal strength, channel utilization, or PHY rate changes.",
      "what_would_help": "WiFi scan results from the WiFry scanner, or iw station dump during capture."
    }
  ],
  "metadata": {
    "provider": "anthropic",
    "model": "claude-sonnet-4-20250514",
    "input_tokens": 3200,
    "output_tokens": 1850,
    "analysis_duration_ms": 4200,
    "analyzed_at": "2026-04-07T15:33:12Z",
    "framework_version": "2.0"
  }
}
```

---

## 12. Migration from v1

### What changes

| Component | v1 (current) | v2 (this spec) |
|---|---|---|
| AI input | Raw tshark text, truncated to 3000 chars/section | Structured CaptureSummary JSON, ~5 KB |
| AI prompt | Single generic system prompt for all captures | Pack-specific prompt templates with rules |
| AI output | `AnalysisResult` with flat `issues` list | `AnalysisResultV2` with evidence citations, confidence, cross-references |
| Pre-analysis | None | Interest detection with anomaly flags and health classification |
| Stats dashboard | Requires AI to see any interpretation | Fully functional without AI; powered by CaptureSummary |
| Comparison | Not supported | Two-capture diff with pre-computed deltas |
| Guardrails | None (trust AI output as-is) | Input validation, output validation, evidence checking |
| Cost | ~$0.02-0.10 (large text input) | ~$0.01-0.03 (structured, smaller input) |

### Backward compatibility

- `AnalysisResult` (v1) remains a valid subset of `AnalysisResultV2`. Existing saved `.analysis.json` files still load.
- The `analyze_capture()` function signature doesn't change externally. It internally switches to the new pipeline when a `.summary.json` exists for the capture.
- If no summary exists (old capture, custom capture that skipped post-processing), fall back to the v1 extraction path.

### Implementation order

1. `CaptureSummary` model + `capture_stats.py` extraction service (backend)
2. `InterestAnnotations` model + threshold rules per pack (backend)
3. `AnalysisResultV2` model (backend, backward compatible)
4. Pack-specific prompt templates (backend)
5. Output validation / guardrails (backend)
6. AI input builder with interest-based narrowing (backend)
7. Comparison delta computation + prompt (backend)
8. Stats dashboard rendering (frontend — uses CaptureSummary, no AI needed)
9. Updated AI diagnosis display with evidence citations and confidence badges (frontend)
10. Comparison UI (frontend)

---

## Appendix A: tshark Extraction Commands by Section

### Protocol Hierarchy

```bash
tshark -r {pcap} -q -z io,phs
```

Parse: tree structure with frame/byte counts. Map to nested `ProtocolBreakdown` list.

### TCP Health

```bash
tshark -r {pcap} -q -z expert
```

Parse: extract counts by severity and group. Compute `retransmission_count` from "TCP Retransmission" + "TCP Fast Retransmission" counts. Compute `retransmission_rate_pct` as `retransmission_count / total_tcp_packets * 100`. SYN/FIN/RST counts extracted with:

```bash
tshark -r {pcap} -T fields -e tcp.flags.syn -e tcp.flags.fin -e tcp.flags.reset -Y "tcp" | sort | uniq -c
```

### TCP Conversations

```bash
tshark -r {pcap} -q -z conv,tcp
```

Parse: tabular output with columns for address pairs, packets, bytes, duration. Sort by total bytes descending, keep top 20.

### UDP Conversations

```bash
tshark -r {pcap} -q -z conv,udp
```

Same parsing strategy as TCP conversations.

### DNS Extraction

```bash
tshark -r {pcap} -T fields \
  -e frame.time_relative \
  -e dns.qry.name \
  -e dns.qry.type \
  -e dns.flags.response \
  -e dns.flags.rcode \
  -e dns.time \
  -e ip.dst \
  -Y "dns" \
  -E header=y -E separator=\t
```

Parse: compute per-domain aggregates (count, avg time, rcodes). Identify resolver IPs from `ip.dst` on query packets. Compute response time percentiles from `dns.time` values.

### Throughput Timeline

```bash
tshark -r {pcap} -q -z io,stat,1
```

Parse: 1-second interval table with bytes and frames columns. Convert to `ThroughputInterval` list. Compute avg/peak/min/std_dev from intervals.

### Endpoints

```bash
tshark -r {pcap} -q -z endpoints,ip
```

Parse: IP addresses with packet/byte counts. Tag RFC1918 status. Sort by bytes, keep top 30.

### ICMP Extraction

```bash
tshark -r {pcap} -T fields \
  -e frame.time_relative \
  -e icmp.type \
  -e icmp.code \
  -e ip.src \
  -e ip.dst \
  -e icmp.resp_time \
  -Y "icmp" \
  -E header=y -E separator=\t
```

Parse: compute per-target request/reply counts and RTT. Types: 8=echo request, 0=echo reply, 3=unreachable, 11=TTL exceeded.

### TLS ClientHello

```bash
tshark -r {pcap} -T fields \
  -e tls.handshake.extensions_server_name \
  -e ip.dst \
  -e tcp.dstport \
  -e tls.handshake.version \
  -Y "tls.handshake.type == 1" \
  -E header=y -E separator=\t
```

Parse: aggregate by SNI, count connections per server name.

---

## Appendix B: Domain Name Sanitization

DNS domain names extracted from captures may contain adversarial content. Apply this sanitization before including in AI input:

```python
import re

_PROMPT_INJECTION_PATTERNS = re.compile(
    r"(ignore.previous|system:|<\||\bprompt\b.*\binjection\b|"
    r"\bassistant\b.*\bresponse\b|\bhuman\b:|\buser\b:)",
    re.IGNORECASE,
)

def sanitize_domain(domain: str) -> str | None:
    """Sanitize a DNS domain name for inclusion in AI prompts.

    Returns None if the domain should be excluded entirely.
    """
    # Strip non-printable characters
    cleaned = "".join(c for c in domain if c.isprintable())

    # Enforce RFC 1035 max length
    if len(cleaned) > 253:
        cleaned = cleaned[:253]

    # Reject domains with prompt-injection-like patterns
    if _PROMPT_INJECTION_PATTERNS.search(cleaned):
        return None

    # Reject domains with excessive label length (>63 chars per label = suspicious)
    labels = cleaned.split(".")
    if any(len(label) > 63 for label in labels):
        return None

    return cleaned
```

---

## Appendix C: Confidence Decision Tree

```
Does the finding cite >=2 corroborating evidence fields?
├── YES: Do the cited values clearly exceed their thresholds?
│   ├── YES → HIGH confidence
│   └── NO (borderline values) → MEDIUM confidence
└── NO (single evidence field):
    ├── Does the single field strongly exceed its threshold (>2x)?
    │   ├── YES → MEDIUM confidence
    │   └── NO → LOW confidence
    └── Is the field null or missing?
        └── YES → InsufficientEvidenceNote (not a finding)
```

The AI is instructed to follow this tree. The output guardrails enforce it:

```python
def enforce_confidence_rules(finding: Finding, summary: CaptureSummary) -> Finding:
    evidence_count = len(finding.evidence)
    if evidence_count == 0:
        return None  # drop finding
    if evidence_count == 1 and finding.confidence == Confidence.HIGH:
        finding.confidence = Confidence.MEDIUM  # downgrade
    if finding.confidence == Confidence.LOW and finding.severity == "critical":
        finding.severity = "high"  # can't be critical with low confidence
    return finding
```
