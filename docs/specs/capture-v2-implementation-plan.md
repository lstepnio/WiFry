# Packet Capture v2 — Implementation Plan

**Status:** Draft
**Date:** 2026-04-07
**Companion specs:** `capture-v2-spec.md` (architecture), `capture-v2-ux-spec.md` (UX design)

---

## 1. System Architecture

### Component Map

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND                                 │
│                                                                 │
│  CaptureManager.tsx (orchestrator)                              │
│  ├── QuickCapture.tsx        — pack card grid + inline config   │
│  ├── ActiveCapture.tsx       — live progress card(s)            │
│  ├── CaptureHistory.tsx      — completed capture list           │
│  └── CaptureDetail.tsx       — stats dashboard + AI diagnosis   │
│                                                                 │
│  api/client.ts               — typed API calls                  │
│  types/index.ts              — CaptureInfo, CaptureSummary, etc │
├─────────────────────────────────────────────────────────────────┤
│                      API LAYER                                  │
│                                                                 │
│  routers/captures.py         — HTTP endpoints (existing + new)  │
├─────────────────────────────────────────────────────────────────┤
│                    SERVICE LAYER                                │
│                                                                 │
│  services/capture.py         — capture engine (dumpcap mgmt)    │
│  services/capture_stats.py   — NEW: stat extraction + parsing   │
│  services/capture_retention.py — NEW: pruning + disk management │
│  services/ai_analyzer.py     — AI pipeline (modified)           │
│  services/session_manager.py — session/artifact linkage         │
├─────────────────────────────────────────────────────────────────┤
│                    MODEL LAYER                                  │
│                                                                 │
│  models/capture.py           — data models (extended)           │
│  models/analysis_packs.py    — NEW: pack configs + BPF + queries│
├─────────────────────────────────────────────────────────────────┤
│                    INFRASTRUCTURE                               │
│                                                                 │
│  utils/shell.py              — subprocess execution (unchanged) │
│  services/storage.py         — path resolution (unchanged)      │
│  config.py                   — settings (add capture defaults)  │
└─────────────────────────────────────────────────────────────────┘
```

### Responsibilities

| Component | Owns | Does NOT own |
|-----------|------|-------------|
| `capture.py` | Process lifecycle (start/stop/monitor), ring buffer management, segment merge | Stat extraction, AI calls, retention |
| `capture_stats.py` | tshark stat queries, raw output parsing, summary JSON generation | Process management, AI calls |
| `capture_retention.py` | Disk usage tracking, age-based pruning, count-based pruning | Capture lifecycle |
| `ai_analyzer.py` | AI prompt construction, provider calls, response parsing | Stat extraction (delegates to capture_stats) |
| `analysis_packs.py` | Pack definitions (BPF, duration, stat queries, AI focus) | Everything else — pure config |
| `captures.py` (router) | HTTP handling, request validation, orchestration | Business logic (delegates to services) |

---

## 2. Phased Implementation Plan

### Phase 1 — Foundation (scope: 1 sprint)

**Goal:** Switch to dumpcap, add ring buffer, add analysis packs model, add structured stat extraction, add concurrent limit and retention. The capture workflow is better even before the frontend changes.

#### Backend Changes

**2.1.1 — Analysis Packs Model**

New file: `backend/app/models/analysis_packs.py`

```python
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel


class AnalysisPack(str, Enum):
    CONNECTIVITY = "connectivity"
    DNS = "dns"
    HTTPS = "https"
    STREAMING = "streaming"
    SECURITY = "security"
    CUSTOM = "custom"


class PackConfig(BaseModel):
    name: str
    description: str
    subtitle: str                      # one-line for card UI
    bpf: str                           # pre-built BPF filter
    default_duration_secs: int
    default_max_size_mb: int
    ring_buffer: bool
    ring_buffer_segment_mb: int
    ring_buffer_max_segments: int
    stat_queries: List[str]            # which tshark -z queries to run
    ai_focus: List[str]                # AI prompt focus areas
    summary_fields: List[str]          # which summary sections to populate


PACK_CONFIGS: Dict[AnalysisPack, PackConfig] = {
    AnalysisPack.CONNECTIVITY: PackConfig(
        name="Connectivity Check",
        description="Basic reachability, DNS, and TCP connection setup",
        subtitle="Can you reach the network?",
        bpf="icmp or (tcp[tcpflags] & tcp-syn != 0) or udp port 53",
        default_duration_secs=30,
        default_max_size_mb=50,
        ring_buffer=True,
        ring_buffer_segment_mb=10,
        ring_buffer_max_segments=5,
        stat_queries=["io_phs", "expert", "endpoints_ip", "dns", "icmp"],
        ai_focus=["packet loss", "unreachable hosts", "DNS failures", "gateway health"],
        summary_fields=["protocols", "tcp_health", "dns", "expert_alerts"],
    ),
    AnalysisPack.DNS: PackConfig(
        name="DNS Troubleshoot",
        description="DNS lookup speed, failures, and anomalies",
        subtitle="Are lookups fast and correct?",
        bpf="udp port 53 or tcp port 53",
        default_duration_secs=60,
        default_max_size_mb=20,
        ring_buffer=True,
        ring_buffer_segment_mb=5,
        ring_buffer_max_segments=4,
        stat_queries=["io_phs", "io_stat", "dns"],
        ai_focus=["slow lookups (>200ms)", "NXDOMAIN", "SERVFAIL", "unusual patterns", "DNS hijacking"],
        summary_fields=["protocols", "dns", "throughput"],
    ),
    AnalysisPack.HTTPS: PackConfig(
        name="HTTPS / Web",
        description="TCP health, TLS setup, and retransmissions on web traffic",
        subtitle="Are web requests completing?",
        bpf="tcp port 80 or tcp port 443 or tcp port 8080",
        default_duration_secs=60,
        default_max_size_mb=100,
        ring_buffer=True,
        ring_buffer_segment_mb=10,
        ring_buffer_max_segments=10,
        stat_queries=["io_phs", "conv_tcp", "io_stat", "expert"],
        ai_focus=["slow connections", "retransmission rate", "RST storms", "TLS errors"],
        summary_fields=["protocols", "tcp_health", "top_conversations", "throughput", "expert_alerts"],
    ),
    AnalysisPack.STREAMING: PackConfig(
        name="Streaming / Video",
        description="Throughput stability, retransmission bursts, CDN health",
        subtitle="Why is the video buffering?",
        bpf="tcp port 80 or tcp port 443 or udp portrange 1024-65535",
        default_duration_secs=120,
        default_max_size_mb=100,
        ring_buffer=True,
        ring_buffer_segment_mb=10,
        ring_buffer_max_segments=10,
        stat_queries=["conv_tcp", "io_stat", "expert", "dns"],
        ai_focus=[
            "throughput dips below ABR thresholds (2/5/10/15 Mbps)",
            "retransmission bursts correlated with throughput drops",
            "CDN resolution patterns", "UDP packet loss",
        ],
        summary_fields=["protocols", "tcp_health", "top_conversations", "throughput", "dns", "expert_alerts"],
    ),
    AnalysisPack.SECURITY: PackConfig(
        name="Security Scan",
        description="Unexpected connections, rogue DNS, scan patterns",
        subtitle="Is there unexpected traffic?",
        bpf="",  # empty = capture all
        default_duration_secs=60,
        default_max_size_mb=100,
        ring_buffer=True,
        ring_buffer_segment_mb=10,
        ring_buffer_max_segments=10,
        stat_queries=["io_phs", "conv_tcp", "endpoints_ip", "dns"],
        ai_focus=[
            "unexpected outbound connections", "DNS exfiltration",
            "port scanning", "ARP spoofing", "non-RFC1918 sources",
        ],
        summary_fields=["protocols", "tcp_health", "top_conversations", "dns", "expert_alerts"],
    ),
    AnalysisPack.CUSTOM: PackConfig(
        name="Custom Capture",
        description="Full control over filters, limits, and analysis",
        subtitle="Advanced capture with manual configuration",
        bpf="",
        default_duration_secs=300,
        default_max_size_mb=100,
        ring_buffer=False,
        ring_buffer_segment_mb=10,
        ring_buffer_max_segments=10,
        stat_queries=["io_phs", "conv_tcp", "io_stat", "expert", "dns"],
        ai_focus=["retransmissions", "latency", "errors"],
        summary_fields=["protocols", "tcp_health", "top_conversations", "throughput", "dns", "expert_alerts"],
    ),
}
```

**2.1.2 — Extended Capture Models**

Changes to `backend/app/models/capture.py`:

```python
# New enum value
class CaptureStatus(str, Enum):
    RUNNING = "running"
    PROCESSING = "processing"   # NEW — post-processing in progress
    COMPLETED = "completed"
    STOPPED = "stopped"
    ERROR = "error"


# Extended StartCaptureRequest
class StartCaptureRequest(BaseModel):
    interface: str
    name: str = ""
    filters: CaptureFilters = Field(default_factory=CaptureFilters)
    analysis_pack: AnalysisPack = AnalysisPack.CUSTOM  # NEW
    max_packets: int = Field(default=0, ge=0, le=1_000_000)  # 0 = no limit
    max_duration_secs: int = Field(default=0, ge=0, le=3600)  # 0 = use pack default
    max_file_size_mb: int = Field(default=0, ge=0, le=200)    # 0 = use pack default
    ring_buffer: Optional[bool] = None      # None = use pack default
    segment_size_mb: int = Field(default=0, ge=0, le=50)  # 0 = use pack default


# Extended CaptureInfo
class CaptureInfo(BaseModel):
    id: str
    name: str
    interface: str
    status: CaptureStatus
    analysis_pack: str = "custom"           # NEW
    filters: CaptureFilters = Field(default_factory=CaptureFilters)
    bpf_expression: str = ""
    started_at: Optional[str] = None
    stopped_at: Optional[str] = None
    packet_count: int = 0
    file_size_bytes: int = 0
    pcap_path: str = ""
    error: Optional[str] = None
    ring_buffer_enabled: bool = False       # NEW
    segment_count: int = 0                  # NEW
    summary_available: bool = False         # NEW
    analysis_available: bool = False        # NEW


# New model for structured summary
class CaptureSummary(BaseModel):
    capture_id: str
    analysis_pack: str
    duration_secs: float = 0
    total_packets: int = 0
    total_bytes: int = 0

    protocols: Dict[str, Any] = {}          # {TCP: {packets, bytes, pct}, ...}
    tcp_health: Dict[str, Any] = {}         # {retransmission_count, retransmission_rate_pct, ...}
    top_conversations: List[Dict[str, Any]] = []
    dns: Dict[str, Any] = {}                # {total_queries, nxdomain_count, ...}
    throughput: Dict[str, Any] = {}         # {avg_mbps, peak_mbps, intervals: [...]}
    expert_alerts: Dict[str, Any] = {}      # {errors, warnings, top_alerts: [...]}

    extracted_at: Optional[str] = None
```

**2.1.3 — Switch to dumpcap + Ring Buffer**

Changes to `backend/app/services/capture.py`:

```python
# New constants
_capture_semaphore = asyncio.Semaphore(2)
_post_process_lock = asyncio.Lock()

RETENTION_MAX_COUNT = 20
RETENTION_MAX_BYTES = 500 * 1024 * 1024  # 500 MB
DISK_SPACE_MIN_BYTES = 200 * 1024 * 1024  # 200 MB


async def start_capture(req: StartCaptureRequest) -> CaptureInfo:
    """Start a new capture using dumpcap (ring buffer) or tshark (legacy single-file)."""

    # --- Resource checks ---
    if not _capture_semaphore._value:  # all slots taken
        raise HTTPException(429, "Maximum concurrent captures reached (2). Stop a running capture first.")

    disk_free = shutil.disk_usage(_captures_dir()).free
    if disk_free < DISK_SPACE_MIN_BYTES:
        raise HTTPException(507, f"Insufficient disk space ({disk_free // (1024*1024)} MB free, need 200 MB).")

    # --- Resolve pack config ---
    pack = PACK_CONFIGS[req.analysis_pack]
    duration = req.max_duration_secs or pack.default_duration_secs
    max_size = req.max_file_size_mb or pack.default_max_size_mb
    use_ring = req.ring_buffer if req.ring_buffer is not None else pack.ring_buffer
    seg_size = req.segment_size_mb or pack.ring_buffer_segment_mb
    seg_count = pack.ring_buffer_max_segments

    # --- Build BPF ---
    if req.analysis_pack != AnalysisPack.CUSTOM:
        bpf = pack.bpf
    else:
        bpf = req.filters.to_bpf()

    # --- Generate ID and paths ---
    capture_id = uuid.uuid4().hex[:12]
    name = req.name or f"{req.analysis_pack.value}-{capture_id[:6]}"
    pcap_file = _pcap_path(capture_id)
    segments_dir = _captures_dir() / f"{capture_id}_segments"

    # --- Build command ---
    if use_ring:
        segments_dir.mkdir(parents=True, exist_ok=True)
        seg_pcap = segments_dir / f"{capture_id}.pcap"
        cmd = [
            "dumpcap",
            "-i", req.interface,
            "-b", f"filesize:{seg_size * 1024}",
            "-b", f"files:{seg_count}",
            "-a", f"duration:{duration}",
            "-w", str(seg_pcap),
        ]
        if bpf:
            cmd.extend(["-f", bpf])
    else:
        cmd = [
            "tshark",
            "-i", req.interface,
            "-c", str(req.max_packets or pack.default_max_size_mb * 100),  # rough estimate
            "-a", f"duration:{duration}",
            "-a", f"filesize:{max_size * 1024}",
            "-w", str(pcap_file),
        ]
        if bpf:
            cmd.extend(["-f", bpf])

    # --- Launch ---
    async with _capture_semaphore:
        info = CaptureInfo(
            id=capture_id,
            name=name,
            interface=req.interface,
            status=CaptureStatus.RUNNING,
            analysis_pack=req.analysis_pack.value,
            filters=req.filters,
            bpf_expression=bpf,
            started_at=datetime.now(timezone.utc).isoformat(),
            pcap_path=str(pcap_file),
            ring_buffer_enabled=use_ring,
        )
        # ... launch subprocess, register monitor task (same pattern as current)
```

**Segment merge after capture stops** (added to `_monitor_capture`):

```python
async def _finalize_capture(capture_id: str):
    """Post-capture: merge segments, extract stats, enforce retention."""
    info = _captures[capture_id]
    segments_dir = _captures_dir() / f"{capture_id}_segments"

    # --- Merge ring buffer segments ---
    if info.ring_buffer_enabled and segments_dir.exists():
        info.status = CaptureStatus.PROCESSING
        _save_metadata(info)

        segment_files = sorted(segments_dir.glob("*.pcap"))
        info.segment_count = len(segment_files)

        if segment_files:
            merged_path = _pcap_path(capture_id)
            merge_args = ["mergecap", "-w", str(merged_path)] + [str(f) for f in segment_files]
            result = await run(*merge_args, timeout=120)
            if result.success:
                # Clean up segments
                shutil.rmtree(segments_dir, ignore_errors=True)
            else:
                info.error = f"Segment merge failed: {result.stderr[:200]}"
                info.status = CaptureStatus.ERROR
                _save_metadata(info)
                return

    # --- Fix ownership ---
    pcap_path = _pcap_path(capture_id)
    if pcap_path.exists():
        await run("chmod", "644", str(pcap_path), sudo=True, check=False)
        await run("chown", "wifry:wifry", str(pcap_path), sudo=True, check=False)
        info.file_size_bytes = pcap_path.stat().st_size

    # --- Count packets ---
    info.packet_count = await _count_packets(str(pcap_path))

    # --- Extract stats ---
    from . import capture_stats
    async with _post_process_lock:
        summary = await capture_stats.extract_and_save(capture_id, info.analysis_pack)
        info.summary_available = summary is not None

    # --- Update final status ---
    info.stopped_at = datetime.now(timezone.utc).isoformat()
    if info.status == CaptureStatus.PROCESSING:
        info.status = CaptureStatus.COMPLETED
    _save_metadata(info)

    # --- Retention check ---
    from . import capture_retention
    await capture_retention.enforce()
```

**2.1.4 — Structured Stat Extraction Service**

New file: `backend/app/services/capture_stats.py`

```python
"""Extract and parse tshark statistics into structured summary JSON."""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..models.analysis_packs import PACK_CONFIGS, AnalysisPack
from ..models.capture import CaptureSummary
from ..utils.shell import run
from . import storage

logger = logging.getLogger(__name__)

# --- tshark query definitions ---

STAT_QUERIES = {
    "io_phs": ["-q", "-z", "io,phs"],
    "conv_tcp": ["-q", "-z", "conv,tcp"],
    "conv_udp": ["-q", "-z", "conv,udp"],
    "io_stat": ["-q", "-z", "io,stat,1"],
    "expert": ["-q", "-z", "expert"],
    "endpoints_ip": ["-q", "-z", "endpoints,ip"],
    "dns": [
        "-Y", "dns.flags.response == 0",
        "-T", "fields",
        "-e", "frame.time_relative",
        "-e", "ip.src",
        "-e", "dns.qry.name",
        "-e", "dns.qry.type",
    ],
    "icmp": [
        "-Y", "icmp",
        "-T", "fields",
        "-e", "frame.time_relative",
        "-e", "ip.src",
        "-e", "ip.dst",
        "-e", "icmp.type",
        "-e", "icmp.code",
    ],
}


async def extract_and_save(capture_id: str, pack_name: str) -> Optional[CaptureSummary]:
    """Run pack-specific tshark queries and build structured summary."""
    captures_dir = storage.ensure_data_path("captures")
    pcap_path = captures_dir / f"{capture_id}.pcap"
    if not pcap_path.exists():
        return None

    pack = PACK_CONFIGS.get(AnalysisPack(pack_name), PACK_CONFIGS[AnalysisPack.CUSTOM])

    # Run tshark queries for this pack
    raw_stats: Dict[str, str] = {}
    for query_key in pack.stat_queries:
        if query_key not in STAT_QUERIES:
            continue
        args = ["tshark", "-r", str(pcap_path)] + STAT_QUERIES[query_key]
        result = await run(*args, sudo=True, check=False, timeout=60)
        raw_stats[query_key] = result.stdout if result.success else ""

    # Parse raw output into structured summary
    summary = CaptureSummary(
        capture_id=capture_id,
        analysis_pack=pack_name,
        extracted_at=datetime.now(timezone.utc).isoformat(),
    )

    # Populate fields based on available stats
    if "io_phs" in raw_stats:
        summary.protocols = _parse_protocol_hierarchy(raw_stats["io_phs"])
    if "conv_tcp" in raw_stats:
        summary.top_conversations = _parse_tcp_conversations(raw_stats["conv_tcp"])
    if "io_stat" in raw_stats:
        summary.throughput = _parse_io_stats(raw_stats["io_stat"])
    if "expert" in raw_stats:
        summary.expert_alerts = _parse_expert_info(raw_stats["expert"])
        summary.tcp_health = _derive_tcp_health(summary.expert_alerts, summary.top_conversations)
    if "dns" in raw_stats:
        summary.dns = _parse_dns_queries(raw_stats["dns"])

    # Derive totals from protocol hierarchy
    if summary.protocols:
        summary.total_packets = sum(p.get("packets", 0) for p in summary.protocols.values())
        summary.total_bytes = sum(p.get("bytes", 0) for p in summary.protocols.values())

    # Save
    summary_path = captures_dir / f"{capture_id}.summary.json"
    summary_path.write_text(summary.model_dump_json(indent=2))
    return summary


def get_summary(capture_id: str) -> Optional[CaptureSummary]:
    """Load a previously saved summary from disk."""
    captures_dir = storage.ensure_data_path("captures")
    path = captures_dir / f"{capture_id}.summary.json"
    if not path.exists():
        return None
    return CaptureSummary.model_validate_json(path.read_text())


# --- Parsers (each takes raw tshark stdout, returns typed dict/list) ---

def _parse_protocol_hierarchy(raw: str) -> Dict[str, Any]:
    """Parse `tshark -z io,phs` into {protocol: {packets, bytes, pct}}."""
    protocols = {}
    for line in raw.strip().splitlines():
        # Format: "  eth:ip:tcp    frames:12345 bytes:6789012"
        match = re.match(r'\s*([\w:]+)\s+frames:(\d+)\s+bytes:(\d+)', line)
        if match:
            proto_chain = match.group(1)
            top_proto = proto_chain.split(":")[-1].upper()
            frames = int(match.group(2))
            nbytes = int(match.group(3))
            if top_proto in ("TCP", "UDP", "ICMP", "DNS", "TLS", "QUIC", "HTTP"):
                if top_proto not in protocols:
                    protocols[top_proto] = {"packets": 0, "bytes": 0}
                protocols[top_proto]["packets"] += frames
                protocols[top_proto]["bytes"] += nbytes

    total_pkts = sum(p["packets"] for p in protocols.values()) or 1
    for proto in protocols.values():
        proto["pct"] = round(proto["packets"] / total_pkts * 100, 1)
    return protocols


def _parse_tcp_conversations(raw: str) -> List[Dict[str, Any]]:
    """Parse `tshark -z conv,tcp` into top 10 conversations by bytes."""
    conversations = []
    for line in raw.strip().splitlines():
        # Skip headers and separators
        parts = line.split()
        if len(parts) < 10 or "<->" not in line:
            continue
        try:
            # Format: addr_a:port <-> addr_b:port  pkts_ab bytes_ab pkts_ba bytes_ba pkts bytes rel_start duration
            left, right = line.split("<->")
            left_parts = left.strip().rsplit(":", 1)
            right_parts = right.strip().split()
            src = left_parts[0]
            src_port = int(left_parts[1]) if len(left_parts) > 1 else 0
            dst_parts = right_parts[0].rsplit(":", 1)
            dst = dst_parts[0]
            dst_port = int(dst_parts[1]) if len(dst_parts) > 1 else 0
            # Total packets and bytes are at indices 5,6 after the arrow portion
            total_packets = int(right_parts[5]) if len(right_parts) > 5 else 0
            total_bytes = int(right_parts[6]) if len(right_parts) > 6 else 0
            conversations.append({
                "src": src, "src_port": src_port,
                "dst": dst, "dst_port": dst_port,
                "packets": total_packets, "bytes": total_bytes,
            })
        except (ValueError, IndexError):
            continue

    # Sort by bytes descending, return top 10
    conversations.sort(key=lambda c: c.get("bytes", 0), reverse=True)
    return conversations[:10]


def _parse_io_stats(raw: str) -> Dict[str, Any]:
    """Parse `tshark -z io,stat,1` into throughput timeline."""
    intervals = []
    for line in raw.strip().splitlines():
        # Format: | 0.000 <> 1.000 | 123 | 45678 |
        match = re.match(r'\|\s*([\d.]+)\s*<>\s*([\d.]+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|', line)
        if match:
            start_sec = float(match.group(1))
            nbytes = int(match.group(4))
            intervals.append({"second": int(start_sec), "bytes": nbytes})

    if not intervals:
        return {"avg_mbps": 0, "peak_mbps": 0, "min_mbps": 0, "intervals": []}

    mbps_values = [(i["bytes"] * 8) / 1_000_000 for i in intervals]
    return {
        "avg_mbps": round(sum(mbps_values) / len(mbps_values), 2),
        "peak_mbps": round(max(mbps_values), 2),
        "min_mbps": round(min(mbps_values), 2),
        "intervals": intervals,
    }


def _parse_expert_info(raw: str) -> Dict[str, Any]:
    """Parse `tshark -z expert` into severity counts and top alerts."""
    severity_counts = {"errors": 0, "warnings": 0, "notes": 0, "chats": 0}
    alert_counts: Dict[str, int] = {}

    for line in raw.strip().splitlines():
        line_lower = line.lower().strip()
        for severity in ("error", "warning", "note", "chat"):
            if line_lower.startswith(severity) or f"  {severity}" in line_lower:
                severity_counts[f"{severity}s" if not severity.endswith("s") else severity] += 1
                # Extract message after severity
                msg = line.strip()
                alert_counts[msg] = alert_counts.get(msg, 0) + 1
                break

    top_alerts = sorted(alert_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    return {
        **severity_counts,
        "top_alerts": [{"message": msg, "count": count} for msg, count in top_alerts],
    }


def _parse_dns_queries(raw: str) -> Dict[str, Any]:
    """Parse DNS field extraction into query summary."""
    queries = []
    domain_counts: Dict[str, int] = {}
    for line in raw.strip().splitlines():
        fields = line.split("\t")
        if len(fields) >= 4:
            time_rel, src, qname, qtype = fields[0], fields[1], fields[2], fields[3]
            queries.append({"time": float(time_rel or 0), "src": src, "domain": qname, "type": qtype})
            domain_counts[qname] = domain_counts.get(qname, 0) + 1

    top_domains = sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    return {
        "total_queries": len(queries),
        "unique_domains": len(domain_counts),
        "top_queried": [{"domain": d, "count": c} for d, c in top_domains],
    }


def _derive_tcp_health(expert: Dict[str, Any], conversations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Derive TCP health metrics from expert info and conversation data."""
    retx_count = 0
    dup_ack_count = 0
    zero_window = 0
    rst_count = 0

    for alert in expert.get("top_alerts", []):
        msg = alert.get("message", "").lower()
        count = alert.get("count", 0)
        if "retransmission" in msg:
            retx_count += count
        elif "duplicate ack" in msg:
            dup_ack_count += count
        elif "zero window" in msg:
            zero_window += count
        elif "rst" in msg:
            rst_count += count

    total_tcp = sum(c.get("packets", 0) for c in conversations) or 1
    return {
        "retransmission_count": retx_count,
        "retransmission_rate_pct": round(retx_count / total_tcp * 100, 2),
        "duplicate_ack_count": dup_ack_count,
        "zero_window_count": zero_window,
        "rst_count": rst_count,
    }
```

**2.1.5 — Retention Service**

New file: `backend/app/services/capture_retention.py`

```python
"""Auto-retention: prune old captures to stay within disk and count budgets."""

import logging
import shutil
from pathlib import Path

from . import capture as capture_svc
from . import session_manager, storage

logger = logging.getLogger(__name__)

MAX_COUNT = 20
MAX_BYTES = 500 * 1024 * 1024  # 500 MB
MAX_AGE_DAYS = 7


async def enforce():
    """Delete oldest completed captures until within budget.

    Exempt: running captures, captures linked to an active session.
    """
    all_captures = await capture_svc.list_captures()
    active_session_id = session_manager.get_active_session_id()

    # Filter to deletable captures (completed/stopped/error, not in active session)
    deletable = []
    for cap in all_captures:
        if cap.status in ("running", "processing"):
            continue
        # TODO: check if linked to active session (requires artifact lookup)
        deletable.append(cap)

    # Sort oldest first
    deletable.sort(key=lambda c: c.started_at or "")

    # Check count
    pruned = []
    while len(all_captures) - len(pruned) > MAX_COUNT and deletable:
        target = deletable.pop(0)
        await capture_svc.delete_capture(target.id)
        pruned.append(target)
        all_captures = [c for c in all_captures if c.id != target.id]

    # Check total size
    total_bytes = sum(c.file_size_bytes for c in all_captures if c.id not in {p.id for p in pruned})
    while total_bytes > MAX_BYTES and deletable:
        target = deletable.pop(0)
        total_bytes -= target.file_size_bytes
        await capture_svc.delete_capture(target.id)
        pruned.append(target)

    if pruned:
        freed = sum(p.file_size_bytes for p in pruned)
        logger.info(
            "capture.retention.pruned",
            extra={"count": len(pruned), "freed_bytes": freed},
        )

    return pruned
```

**2.1.6 — Modified AI Analyzer**

Changes to `backend/app/services/ai_analyzer.py`:

```python
async def analyze_capture(capture_id: str, request: AnalysisRequest) -> AnalysisResult:
    """Analyze a capture using its structured summary (not raw tshark output)."""

    # Try to load structured summary first (new path)
    from . import capture_stats
    summary = capture_stats.get_summary(capture_id)

    if summary:
        # New path: use structured summary JSON
        prompt = _build_summary_prompt(summary, request)
    else:
        # Legacy path: fall back to raw tshark stats
        stats = await capture_service.get_capture_stats(capture_id)
        if not stats:
            raise HTTPException(404, "No capture data found")
        prompt = _build_analysis_prompt(stats, request)

    # ... rest of AI call is unchanged ...


def _build_summary_prompt(summary: CaptureSummary, request: AnalysisRequest) -> str:
    """Build AI prompt from structured summary JSON."""
    pack = PACK_CONFIGS.get(AnalysisPack(summary.analysis_pack), PACK_CONFIGS[AnalysisPack.CUSTOM])

    lines = [request.prompt, ""]
    lines.append(f"## Analysis Pack: {pack.name}")
    lines.append(f"Focus areas: {', '.join(pack.ai_focus)}")
    lines.append("")
    lines.append("## Capture Statistics (structured JSON)")
    lines.append(summary.model_dump_json(indent=2, exclude={"capture_id", "extracted_at"}))

    return "\n".join(lines)
```

**2.1.7 — New API Endpoints**

Additions to `backend/app/routers/captures.py`:

```python
from ..models.analysis_packs import AnalysisPack, PACK_CONFIGS

@router.get("/packs")
async def list_packs():
    """Return available analysis pack configurations for the UI."""
    return {
        pack.value: {
            "name": config.name,
            "description": config.description,
            "subtitle": config.subtitle,
            "bpf": config.bpf,
            "default_duration_secs": config.default_duration_secs,
            "default_max_size_mb": config.default_max_size_mb,
            "ring_buffer": config.ring_buffer,
        }
        for pack, config in PACK_CONFIGS.items()
        if pack != AnalysisPack.CUSTOM
    }


@router.get("/{capture_id}/summary")
async def get_summary(capture_id: str):
    """Return the structured statistical summary for a capture."""
    from ..services import capture_stats
    summary = capture_stats.get_summary(capture_id)
    if not summary:
        raise HTTPException(404, "No summary available. Run post-processing or analyze the capture.")
    return summary


@router.get("/status")
async def capture_status():
    """Return system-wide capture resource status."""
    from ..services import capture as cap_svc
    all_captures = await cap_svc.list_captures()
    running = [c for c in all_captures if c.status in ("running", "processing")]
    disk_free = shutil.disk_usage(cap_svc._captures_dir()).free
    total_size = sum(c.file_size_bytes for c in all_captures)
    return {
        "running_count": len(running),
        "max_concurrent": 2,
        "can_start": len(running) < 2 and disk_free > 200 * 1024 * 1024,
        "total_captures": len(all_captures),
        "total_size_bytes": total_size,
        "disk_free_bytes": disk_free,
    }
```

#### Frontend Changes (Phase 1)

Minimal UI changes in phase 1 — focus on plumbing:

1. **Add `analysis_pack` to StartCaptureRequest in API client** — dropdown in the existing form
2. **Render `analysis_pack` badge in capture list rows** — alongside existing status badge
3. **Show `summary_available` indicator** — "Stats ready" text if summary exists
4. **Add `/summary` API call** and render basic key-value summary on CaptureAnalysis
5. **Show "Processing..." status** during post-processing instead of jumping to "completed"

#### Data Model Changes

| Model | Change | Migration |
|-------|--------|-----------|
| `CaptureStatus` | Add `PROCESSING` value | Additive, no migration |
| `StartCaptureRequest` | Add `analysis_pack`, `ring_buffer`, `segment_size_mb` | All optional with defaults, backward compatible |
| `CaptureInfo` | Add `analysis_pack`, `ring_buffer_enabled`, `segment_count`, `summary_available`, `analysis_available` | Defaults to current values for existing captures |
| `CaptureSummary` | New model | New file only |

#### Test Strategy

```
tests/test_analysis_packs.py
  - test_all_packs_have_valid_bpf (no tshark syntax error)
  - test_pack_stat_queries_are_known
  - test_custom_pack_allows_empty_bpf

tests/test_capture_stats.py
  - test_parse_protocol_hierarchy (sample tshark output → expected dict)
  - test_parse_tcp_conversations (sample output → sorted list)
  - test_parse_io_stats (sample output → throughput dict with intervals)
  - test_parse_expert_info (sample output → severity counts + top alerts)
  - test_parse_dns_queries (sample output → query summary)
  - test_extract_and_save_creates_summary_file (mock capture → file exists)

tests/test_capture_retention.py
  - test_enforce_deletes_oldest_over_count_limit
  - test_enforce_deletes_oldest_over_size_limit
  - test_enforce_preserves_running_captures
  - test_enforce_noop_under_limits

tests/test_capture_v2.py
  - test_start_capture_with_pack (verify dumpcap args)
  - test_start_capture_rejects_at_concurrent_limit (429)
  - test_start_capture_rejects_on_low_disk (507)
  - test_finalize_merges_ring_segments
  - test_packs_endpoint_returns_all_packs
  - test_summary_endpoint_404_when_not_available
  - test_capture_status_endpoint
```

---

### Phase 2 — UX Overhaul (scope: 1 sprint)

**Goal:** Implement the redesigned frontend from the UX spec. The backend from phase 1 is stable; this phase is frontend-heavy.

#### Frontend Changes

**2.2.1 — Component Split**

```
CaptureManager.tsx (orchestrator — thin)
├── QuickCapture.tsx
│   ├── PackCard component (5 cards in grid)
│   └── PackConfigBar component (inline config on card click)
├── ActiveCapture.tsx
│   └── CaptureProgressCard component (progress bar, live stats)
├── CaptureHistory.tsx
│   └── CaptureRow component (pack badge, inline summary stats)
└── CaptureDetail.tsx
    ├── CaptureStats section (protocol bars, TCP health, throughput sparkline, conversations, DNS)
    └── CaptureAIDiagnosis section (on-demand AI with evidence/confidence)
```

**2.2.2 — QuickCapture Component**

```tsx
// Pseudocode — actual component structure
function QuickCapture({ onStart, canStart, runningCount }) {
  const [selectedPack, setSelectedPack] = useState<string | null>(null);
  const [duration, setDuration] = useState(0);
  const [iface, setIface] = useState("wlan0");
  const packs = useApi(fetchPacks);  // GET /api/v1/captures/packs

  return (
    <section>
      <SectionHeader title="Quick Capture" subtitle="Pick a troubleshooting mode..." />

      <div className="grid grid-cols-5 gap-3">  {/* or flex-wrap on mobile */}
        {packs.map(pack => (
          <PackCard
            key={pack.id}
            pack={pack}
            selected={selectedPack === pack.id}
            disabled={!canStart}
            onClick={() => setSelectedPack(pack.id)}
          />
        ))}
      </div>

      {selectedPack && (
        <PackConfigBar
          pack={packs.find(p => p.id === selectedPack)}
          duration={duration}
          iface={iface}
          onDurationChange={setDuration}
          onIfaceChange={setIface}
          onStart={() => onStart({ analysis_pack: selectedPack, interface: iface, max_duration_secs: duration })}
          onCancel={() => setSelectedPack(null)}
        />
      )}

      <div className="mt-2 text-xs text-gray-500">
        Need more control? <button onClick={showCustomForm} className="text-blue-400 underline">Custom Capture</button>
      </div>
    </section>
  );
}
```

**2.2.3 — CaptureDetail with Stats Dashboard**

The stats dashboard renders `CaptureSummary` JSON. Key visual elements:

- **Protocol bars:** Horizontal bar chart using CSS widths (`width: ${pct}%`)
- **Throughput sparkline:** Inline SVG polyline from `summary.throughput.intervals[]`
- **TCP health table:** Key/value with status icons (green/yellow/red based on thresholds)
- **Top conversations:** Monospace table, sorted by bytes
- **DNS summary:** Key metrics + top queried domains

No chart library needed. CSS width bars + SVG polyline cover all cases.

#### Backend Changes (Phase 2)

Minimal — mostly polish:

1. **Add `elapsed_secs` and `bytes_per_sec` to live `CaptureInfo`** — computed in `_monitor_capture`
2. **Add segment count tracking** — count files in `_segments/` dir during monitoring
3. **Expose capture disk usage in `/status`** — already done in phase 1

#### Test Strategy

```
Frontend tests (vitest):
  - QuickCapture renders 5 pack cards
  - Clicking a card expands config bar
  - Config bar shows pack-specific default duration
  - Start button calls API with correct analysis_pack
  - Cards are disabled when canStart=false
  - ActiveCapture shows progress bar proportional to elapsed/duration
  - CaptureHistory shows inline summary stats for captures with summary_available=true
  - CaptureDetail renders protocol bars, TCP health, throughput sparkline
  - CaptureDetail shows "Get AI Diagnosis" button
```

---

### Phase 3 — Background Capture & Session Timeline (scope: 1 sprint)

**Goal:** Always-on ring buffer capture, snapshot preserve, and session timeline events.

#### Scope

- Background capture toggle (always-on dumpcap when AP is active)
- "Preserve last Ns" button to snapshot ring buffer
- Session timeline events for captures and impairments
- Comparative analysis (side-by-side two captures)

#### Backend Changes

**2.3.1 — Background Capture Service**

```python
# backend/app/services/background_capture.py

_background_process: Optional[asyncio.subprocess.Process] = None
_background_dir: Optional[Path] = None
RING_DURATION_SECS = 300  # 5-minute rolling window
SEGMENT_SIZE_MB = 10
MAX_SEGMENTS = 6  # 60 MB rolling window


async def start():
    """Start always-on ring buffer capture on AP interface."""
    global _background_process, _background_dir
    if _background_process:
        return  # already running

    iface = settings.ap_interface or "wlan0"
    _background_dir = storage.ensure_data_path("captures") / "_background"
    _background_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "dumpcap", "-i", iface,
        "-b", f"filesize:{SEGMENT_SIZE_MB * 1024}",
        "-b", f"files:{MAX_SEGMENTS}",
        "-w", str(_background_dir / "bg.pcap"),
    ]
    _background_process = await asyncio.create_subprocess_exec(
        "sudo", *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )


async def stop():
    """Stop background capture."""
    global _background_process
    if _background_process:
        _background_process.terminate()
        try:
            await asyncio.wait_for(_background_process.wait(), timeout=5)
        except asyncio.TimeoutError:
            _background_process.kill()
        _background_process = None


async def preserve(name: str = "", last_secs: int = 60) -> str:
    """Snapshot the last N seconds from the ring buffer into a named capture."""
    if not _background_dir or not _background_dir.exists():
        raise ValueError("Background capture not running")

    # Get all segment files sorted by mtime (newest last)
    segments = sorted(_background_dir.glob("bg_*.pcap"), key=lambda f: f.stat().st_mtime)
    if not segments:
        raise ValueError("No background capture data available")

    # Merge recent segments into a new capture
    from . import capture as cap_svc
    capture_id = uuid.uuid4().hex[:12]
    merged_path = cap_svc._pcap_path(capture_id)

    merge_args = ["mergecap", "-w", str(merged_path)] + [str(f) for f in segments[-3:]]
    result = await run(*merge_args, timeout=60)
    if not result.success:
        raise RuntimeError(f"Merge failed: {result.stderr[:200]}")

    await run("chmod", "644", str(merged_path), sudo=True, check=False)
    await run("chown", "wifry:wifry", str(merged_path), sudo=True, check=False)

    # Create CaptureInfo for this snapshot
    info = CaptureInfo(
        id=capture_id,
        name=name or f"snapshot-{capture_id[:6]}",
        interface=settings.ap_interface or "wlan0",
        status=CaptureStatus.PROCESSING,
        analysis_pack="custom",
        started_at=datetime.now(timezone.utc).isoformat(),
        pcap_path=str(merged_path),
        file_size_bytes=merged_path.stat().st_size,
    )
    cap_svc._captures[capture_id] = info
    cap_svc._save_metadata(info)

    # Trigger post-processing
    await cap_svc._finalize_capture(capture_id)
    return capture_id
```

**2.3.2 — Session Timeline Events**

```python
# Addition to backend/app/models/session.py

class TimelineEventType(str, Enum):
    SESSION_STARTED = "session_started"
    SESSION_COMPLETED = "session_completed"
    SESSION_PAUSED = "session_paused"
    SESSION_RESUMED = "session_resumed"
    CAPTURE_STARTED = "capture_started"
    CAPTURE_COMPLETED = "capture_completed"
    IMPAIRMENT_APPLIED = "impairment_applied"
    IMPAIRMENT_CLEARED = "impairment_cleared"
    ANOMALY_DETECTED = "anomaly_detected"  # future


class TimelineEvent(BaseModel):
    timestamp: str
    event_type: TimelineEventType
    data: Dict[str, Any] = {}
```

---

## 3. Capture Approach Details

### 3.1 dumpcap for Capture

**When:** All captures (both quick pack and custom, unless `ring_buffer=false` on custom).

**Command:**
```bash
sudo dumpcap -i wlan0 \
  -b filesize:10240 \     # 10 MB per segment
  -b files:10 \           # keep max 10 segments
  -a duration:120 \       # auto-stop after 120s
  -f "tcp port 80 or tcp port 443" \
  -w /var/lib/wifry/captures/{id}_segments/{id}.pcap
```

**Why dumpcap over tshark for capture:**
- 5 MB RSS vs 30-80 MB RSS (no dissector loading)
- Native ring buffer rotation
- Same BPF syntax
- Same capture quality (it's the same engine)

**Fallback to tshark:** Only when `ring_buffer=false` (custom capture, advanced users). This preserves current behavior for users who want a single contiguous pcap.

### 3.2 tshark for Post-Processing

**When:** After capture completes, during the PROCESSING phase.

**Commands (per pack config):**
```bash
# Protocol hierarchy
tshark -r {id}.pcap -q -z io,phs

# TCP conversations (top 10)
tshark -r {id}.pcap -q -z conv,tcp

# Throughput per second
tshark -r {id}.pcap -q -z io,stat,1

# Expert analysis (retransmissions, etc.)
tshark -r {id}.pcap -q -z expert

# DNS queries
tshark -r {id}.pcap -Y "dns.flags.response == 0" -T fields -e frame.time_relative -e ip.src -e dns.qry.name -e dns.qry.type
```

**Serialized:** Only one post-processing pipeline runs at a time (`_post_process_lock`). This prevents tshark from competing with itself for CPU/RAM.

### 3.3 Ring Buffer Rotation

dumpcap handles rotation natively. File naming:
```
{id}_segments/
├── {id}_00001_20260407143200.pcap   # segment 1 (oldest, may be overwritten)
├── {id}_00002_20260407143210.pcap   # segment 2
├── ...
└── {id}_00010_20260407143330.pcap   # segment 10 (newest)
```

On capture stop: `mergecap -w {id}.pcap {id}_segments/*.pcap` → single merged file.
Segments directory deleted after successful merge.

### 3.4 Retention / Pruning

Triggered after every capture finalization. Rules in priority order:
1. Delete captures older than 7 days (any status except running)
2. Delete oldest captures exceeding 20 count
3. Delete oldest captures exceeding 500 MB total
4. Never delete running/processing captures
5. Never delete captures linked to an active session

---

## 4. Derived Analysis Pipeline

```
Raw Capture (.pcap)
    │
    ▼
┌─────────────────────────────┐
│  Post-Processing (auto)     │
│                             │
│  Pack config selects which  │
│  tshark queries to run.     │
│  Each query's raw output    │
│  is parsed into typed dicts.│
│                             │
│  Output: CaptureSummary     │
│  (3-15 KB JSON)             │
└────────────┬────────────────┘
             │
    ┌────────┴────────┐
    ▼                 ▼
┌──────────┐   ┌──────────────┐
│ Stats UI │   │ AI Diagnosis │
│ (free)   │   │ (on-demand)  │
│          │   │              │
│ Renders  │   │ Reads        │
│ summary  │   │ summary JSON │
│ as cards,│   │ + pack focus │
│ charts,  │   │ → LLM call   │
│ tables   │   │ → structured │
│          │   │   response   │
└──────────┘   └──────────────┘
```

**Key property:** The pcap is never sent to the AI. The AI receives a 3-15 KB JSON summary containing typed numbers, not raw text. This is:
- Deterministic in size (not proportional to capture size)
- Cheap in tokens (~2-3K input tokens)
- Structured so the LLM can reason about specific metrics
- Auditable (user can see the same data in the stats dashboard)

---

## 5. Failure Handling

### 5.1 Capture Process Dies

```python
# In _monitor_capture(), after proc.wait() returns:
if proc.returncode not in (0, -15):  # -15 = SIGTERM (normal stop)
    info.status = CaptureStatus.ERROR
    info.error = f"Capture process exited with code {proc.returncode}: {stderr_text[:500]}"
    _save_metadata(info)
    # Still attempt finalization (partial pcap may be analyzable)
    try:
        await _finalize_capture(capture_id)
    except Exception:
        pass
```

### 5.2 Malformed BPF

```python
# Pre-validate BPF before launching capture
async def _validate_bpf(bpf: str, interface: str) -> Optional[str]:
    """Return error message if BPF is invalid, None if valid."""
    result = await run("dumpcap", "-i", interface, "-f", bpf, "-d", sudo=True, timeout=5)
    if not result.success:
        return f"Invalid capture filter: {result.stderr.strip()}"
    return None

# In start_capture():
if bpf:
    error = await _validate_bpf(bpf, req.interface)
    if error:
        raise HTTPException(400, error)
```

### 5.3 Disk Nearly Full

```python
# Pre-check in start_capture()
disk_free = shutil.disk_usage(_captures_dir()).free
if disk_free < DISK_SPACE_MIN_BYTES:
    raise HTTPException(
        507,
        f"Insufficient disk space ({disk_free // (1024*1024)} MB free). "
        f"Delete old captures or connect USB storage."
    )

# Mid-capture check in _monitor_capture()
if info.file_size_bytes > 0 and info.file_size_bytes % (10 * 1024 * 1024) < 2048:
    # Check every ~10 MB of capture
    disk_free = shutil.disk_usage(_captures_dir()).free
    if disk_free < 50 * 1024 * 1024:  # 50 MB emergency floor
        logger.warning("capture.disk_low", extra={"free_mb": disk_free // (1024*1024)})
        await stop_capture(capture_id)
```

### 5.4 CPU Too High

Not actively managed in MVP. dumpcap's CPU footprint is minimal (~5% one core). Post-processing is serialized via lock. Future: monitor `/proc/loadavg` and defer post-processing if load > 3.0.

### 5.5 Interface Disappears

```python
# In _monitor_capture(), when process exits with non-zero:
if "No such device" in stderr_text or "not found" in stderr_text:
    info.error = f"Network interface '{info.interface}' is no longer available."
    info.status = CaptureStatus.ERROR
```

### 5.6 Analysis Timeout

```python
# In ai_analyzer.py — existing timeout on shell commands (60s each).
# Add total post-processing timeout:
async with _post_process_lock:
    try:
        summary = await asyncio.wait_for(
            capture_stats.extract_and_save(capture_id, info.analysis_pack),
            timeout=300,  # 5-minute total timeout
        )
    except asyncio.TimeoutError:
        logger.error("capture.postprocess.timeout", extra={"capture_id": capture_id})
        info.error = "Post-processing timed out after 5 minutes."
```

---

## 6. Observability

### 6.1 Structured Logging

All log events use `logger.info/warning/error` with `extra={}` dict for structured fields.

| Event | Level | Extra Fields |
|-------|-------|-------------|
| `capture.started` | INFO | capture_id, interface, pack, bpf, ring_buffer |
| `capture.stopped` | INFO | capture_id, duration_secs, file_size_bytes, packet_count |
| `capture.error` | ERROR | capture_id, error, returncode |
| `capture.processing` | INFO | capture_id, phase (merge/stats/finalize) |
| `capture.completed` | INFO | capture_id, summary_available, duration_secs |
| `capture.concurrent.rejected` | WARNING | running_count, max_concurrent |
| `capture.disk.low` | WARNING | free_mb, threshold_mb |
| `capture.disk.rejected` | WARNING | free_mb, threshold_mb |
| `capture.retention.pruned` | INFO | count, freed_bytes |
| `capture.bpf.invalid` | WARNING | bpf, error |
| `capture.merge.failed` | ERROR | capture_id, error |
| `capture.stats.extracted` | INFO | capture_id, pack, duration_ms |
| `capture.stats.failed` | ERROR | capture_id, query, error |
| `ai.analysis.started` | INFO | capture_id, provider |
| `ai.analysis.completed` | INFO | capture_id, provider, tokens, duration_ms |
| `ai.analysis.failed` | ERROR | capture_id, provider, error |

### 6.2 Status Model

The `/api/v1/captures/status` endpoint returns system-wide capture health:

```json
{
  "running_count": 1,
  "max_concurrent": 2,
  "can_start": true,
  "total_captures": 14,
  "total_size_bytes": 234567890,
  "disk_free_bytes": 12345678901,
  "retention": {
    "max_count": 20,
    "max_bytes": 524288000,
    "current_count": 14,
    "current_bytes": 234567890
  },
  "background_capture": {
    "active": false,
    "segments": 0,
    "total_bytes": 0
  }
}
```

### 6.3 Capture Lifecycle State Machine

```
              start_capture()
                    │
                    ▼
    ┌─────────── RUNNING ──────────────┐
    │           (dumpcap active)        │
    │                                  │
    │  stop_capture()    proc exits    │
    │       │              │           │
    │       ▼              ▼           │
    │   PROCESSING ◄──────────         │
    │   (merge + stats)                │
    │       │                          │
    │  ┌────┴────┐                     │
    │  ▼         ▼                     │
    │ COMPLETED  ERROR                 │
    │  (success)  (merge/stats failed) │
    │                                  │
    │  proc crashes                    │
    │       │                          │
    │       ▼                          │
    │     ERROR ─────────────────────► │
    └──────────────────────────────────┘
    
    On restart: RUNNING → ERROR (stale reconciliation)
```

---

## 7. API Contracts

### New Endpoints

| Method | Path | Request | Response | Notes |
|--------|------|---------|----------|-------|
| GET | `/api/v1/captures/packs` | — | `Dict[str, PackConfig]` | Pack definitions for UI |
| GET | `/api/v1/captures/status` | — | `CaptureSystemStatus` | Resource budget for UI |
| GET | `/api/v1/captures/{id}/summary` | — | `CaptureSummary` | Structured stats |

### Modified Endpoints

| Method | Path | Change |
|--------|------|--------|
| POST | `/api/v1/captures` | Accepts `analysis_pack`, `ring_buffer`, `segment_size_mb`. Returns 429 at concurrent limit, 507 on low disk. |
| GET | `/api/v1/captures` | Returns extended CaptureInfo with `analysis_pack`, `summary_available`, `analysis_available`. |
| POST | `/api/v1/captures/{id}/analyze` | Uses summary JSON when available, falls back to raw stats. |

### Unchanged Endpoints

| Method | Path |
|--------|------|
| GET | `/api/v1/captures/{id}` |
| POST | `/api/v1/captures/{id}/stop` |
| DELETE | `/api/v1/captures/{id}` |
| GET | `/api/v1/captures/{id}/download` |
| GET | `/api/v1/captures/{id}/analysis` |

---

## 8. File Layout & Naming Convention

```
/var/lib/wifry/captures/
│
├── {capture_id}.json                    # CaptureInfo metadata
├── {capture_id}.pcap                    # Merged pcap (final artifact)
├── {capture_id}.summary.json            # CaptureSummary (structured stats)
├── {capture_id}.analysis.json           # AnalysisResult (AI output)
│
├── {capture_id}_segments/               # Ring buffer segments (temporary)
│   ├── {capture_id}_00001_*.pcap        # Segment 1 (dumpcap auto-names)
│   ├── {capture_id}_00002_*.pcap        # Segment 2
│   └── ...                              # Deleted after merge
│
├── _background/                         # Background capture ring buffer
│   ├── bg_00001_*.pcap                  # Rolling segments (dumpcap manages)
│   ├── bg_00002_*.pcap
│   └── ...                              # Not deleted — continuously rotated
│
└── (legacy captures from v1 — same {id}.json + {id}.pcap pattern, no summary)
```

**Naming rules:**
- `capture_id`: 12 hex chars from UUID (existing, unchanged)
- Metadata: `{id}.json` (existing, extended schema)
- pcap: `{id}.pcap` (existing, unchanged)
- Summary: `{id}.summary.json` (new)
- Analysis: `{id}.analysis.json` (existing, unchanged)
- Segments: `{id}_segments/` directory (new, temporary)
- Background: `_background/` directory (new, leading underscore = system-managed)

---

## 9. Operational Considerations

### Disk Monitoring

| Check | Trigger | Action |
|-------|---------|--------|
| Pre-capture | `start_capture()` | Reject if <200 MB free |
| Mid-capture | Every ~10 MB of capture growth | Stop capture if <50 MB free |
| Post-capture | `_finalize_capture()` | Run retention enforcement |
| Periodic | Every list_captures() call (UI polls at 3s) | Include disk_free in status response |

### SD Card Wear

- Default captures are 30-120 seconds, not continuous. Minimal wear concern.
- Background capture (phase 3) writes continuously. Documentation will recommend USB storage for background mode.
- Ring buffer is sequential write → SD-card friendly (no random I/O).

### Graceful Shutdown

Existing `main.py` shutdown handler already stops all running captures. Phase 1 addition: also stop background capture process and clean up segment directories.

```python
# Addition to main.py lifespan shutdown:
from .services import background_capture
await background_capture.stop()
```

### Backup / Restore

Capture files are under `/var/lib/wifry/captures/` which is already covered by factory reset (allowlist scan from PR #16). Session bundles already include linked capture pcaps. No additional backup mechanism needed.
