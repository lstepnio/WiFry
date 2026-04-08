"""Pydantic models for packet capture and AI analysis.

V2 models add structured CaptureSummary, evidence-based AnalysisResultV2,
interest annotations, and analysis pack support.  V1 AnalysisResult / AnalysisIssue
are retained for backward compatibility with existing saved analyses.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────────

class CaptureStatus(str, Enum):
    RUNNING = "running"
    PROCESSING = "processing"
    COMPLETED = "completed"
    STOPPED = "stopped"
    ERROR = "error"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class HealthBadge(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    INSUFFICIENT = "insufficient"


# ── Capture Filters ──────────────────────────────────────────────────────────

class CaptureFilters(BaseModel):
    """Capture pre-filters mapped to BPF expressions."""

    host: Optional[str] = Field(None, description="Filter by host IP")
    port: Optional[int] = Field(None, ge=1, le=65535, description="Filter by port")
    protocol: Optional[str] = Field(None, description="Protocol: tcp, udp, icmp")
    direction: Optional[str] = Field(None, description="inbound or outbound")
    custom_bpf: Optional[str] = Field(None, description="Raw BPF filter expression")

    def to_bpf(self, interface_ip: str = "") -> str:
        """Convert structured filters to a BPF expression."""
        if self.custom_bpf:
            return self.custom_bpf

        parts: List[str] = []

        if self.protocol:
            parts.append(self.protocol.lower())

        if self.host:
            if self.direction == "inbound":
                parts.append(f"src host {self.host}")
            elif self.direction == "outbound":
                parts.append(f"dst host {self.host}")
            else:
                parts.append(f"host {self.host}")

        if self.port:
            parts.append(f"port {self.port}")

        return " and ".join(parts)


# ── Capture Info ─────────────────────────────────────────────────────────────

class StartCaptureRequest(BaseModel):
    """Request to start a new packet capture."""

    interface: str = Field(..., description="Network interface to capture on")
    name: str = Field("", description="Human-readable name for this capture")
    pack: str = Field("custom", description="Analysis pack: connectivity, dns, https, streaming, security, custom")
    filters: CaptureFilters = Field(default_factory=CaptureFilters)
    max_packets: int = Field(10000, ge=1, le=1000000, description="Max packets to capture")
    max_duration_secs: int = Field(300, ge=1, le=3600, description="Max capture duration")
    max_file_size_mb: int = Field(50, ge=1, le=500, description="Max pcap file size in MB")


class CaptureInfo(BaseModel):
    """Metadata for a capture session."""

    id: str
    name: str
    interface: str
    status: CaptureStatus
    pack: str = "custom"
    filters: CaptureFilters
    bpf_expression: str = ""
    started_at: Optional[str] = None
    stopped_at: Optional[str] = None
    packet_count: int = 0
    file_size_bytes: int = 0
    pcap_path: str = ""
    error: Optional[str] = None
    health_badge: Optional[str] = None
    has_summary: bool = False
    has_analysis: bool = False


# ── CaptureSummary: Typed stats extracted by tshark ──────────────────────────

class ProtocolEntry(BaseModel):
    """A row in the protocol hierarchy."""

    name: str
    frames: int = 0
    bytes: int = 0
    pct: float = 0.0


class ProtocolBreakdown(BaseModel):
    """Protocol hierarchy statistics."""

    total_frames: int = 0
    total_bytes: int = 0
    protocols: List[ProtocolEntry] = Field(default_factory=list)
    unencrypted_pct: float = 0.0


class TcpHealth(BaseModel):
    """TCP connection health metrics."""

    total_segments: int = 0
    retransmission_count: int = 0
    retransmission_pct: float = 0.0
    fast_retransmission_count: int = 0
    duplicate_ack_count: int = 0
    zero_window_count: int = 0
    rst_count: int = 0
    out_of_order_count: int = 0
    window_full_count: int = 0


class Conversation(BaseModel):
    """A TCP/UDP conversation."""

    src: str
    src_port: int = 0
    dst: str
    dst_port: int = 0
    protocol: str = "tcp"
    frames: int = 0
    bytes: int = 0
    duration_secs: float = 0.0
    bps: float = 0.0


class DnsSummary(BaseModel):
    """DNS query/response statistics."""

    total_queries: int = 0
    total_responses: int = 0
    unique_domains: int = 0
    nxdomain_count: int = 0
    servfail_count: int = 0
    timeout_count: int = 0
    avg_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    top_domains: List[Dict[str, Any]] = Field(default_factory=list)


class ThroughputSample(BaseModel):
    """A single throughput measurement over an interval."""

    interval_start: float = 0.0
    interval_end: float = 0.0
    frames: int = 0
    bytes: int = 0
    bps: float = 0.0


class ThroughputSummary(BaseModel):
    """Throughput over time."""

    samples: List[ThroughputSample] = Field(default_factory=list)
    avg_bps: float = 0.0
    max_bps: float = 0.0
    min_bps: float = 0.0
    coefficient_of_variation: float = 0.0


class ExpertEntry(BaseModel):
    """A tshark expert info entry."""

    severity: str = ""
    group: str = ""
    summary: str = ""
    count: int = 0


class ExpertSummary(BaseModel):
    """Expert info statistics."""

    entries: List[ExpertEntry] = Field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    note_count: int = 0
    chat_count: int = 0


class IcmpSummary(BaseModel):
    """ICMP statistics."""

    total_count: int = 0
    echo_request_count: int = 0
    echo_reply_count: int = 0
    unreachable_count: int = 0
    ttl_exceeded_count: int = 0
    avg_rtt_ms: float = 0.0


class EndpointEntry(BaseModel):
    """An IP endpoint."""

    ip: str
    frames: int = 0
    bytes: int = 0
    tx_frames: int = 0
    rx_frames: int = 0


class TlsHandshake(BaseModel):
    """TLS handshake observation."""

    server: str = ""
    sni: str = ""
    version: str = ""
    cipher: str = ""
    handshake_ms: float = 0.0
    resumed: bool = False


class TlsSummary(BaseModel):
    """TLS statistics."""

    total_handshakes: int = 0
    handshake_failure_count: int = 0
    avg_handshake_ms: float = 0.0
    max_handshake_ms: float = 0.0
    versions: Dict[str, int] = Field(default_factory=dict)
    handshakes: List[TlsHandshake] = Field(default_factory=list)


class CaptureMeta(BaseModel):
    """Capture metadata included in summary."""

    capture_id: str
    pack: str = "custom"
    interface: str = ""
    bpf: str = ""
    started_at: str = ""
    stopped_at: str = ""
    duration_secs: float = 0.0
    total_packets: int = 0
    total_bytes: int = 0
    pcap_file_bytes: int = 0


# ── Interest Annotations ────────────────────────────────────────────────────

class AnomalyFlag(BaseModel):
    """A flagged anomaly from threshold detection."""

    metric: str
    value: float
    threshold: float
    severity: str
    label: str


class InterestWindow(BaseModel):
    """A time window of interest."""

    start_secs: float
    end_secs: float
    reason: str


class FocusFlow(BaseModel):
    """A flow that warrants closer AI inspection."""

    src: str
    dst: str
    reason: str


class InterestAnnotations(BaseModel):
    """Pre-AI interest detection results."""

    anomaly_flags: List[AnomalyFlag] = Field(default_factory=list)
    interest_windows: List[InterestWindow] = Field(default_factory=list)
    focus_flows: List[FocusFlow] = Field(default_factory=list)
    health_badge: HealthBadge = HealthBadge.INSUFFICIENT


class CaptureSummary(BaseModel):
    """Structured capture statistics — the single source of truth for
    both the stats dashboard and AI analysis input.

    Generated by deterministic tshark queries after capture completes.
    Typically 3-8 KB JSON (~20 KB max for very busy captures).
    """

    meta: CaptureMeta
    protocol_breakdown: Optional[ProtocolBreakdown] = None
    tcp_health: Optional[TcpHealth] = None
    conversations: List[Conversation] = Field(default_factory=list)
    dns: Optional[DnsSummary] = None
    throughput: Optional[ThroughputSummary] = None
    expert: Optional[ExpertSummary] = None
    icmp: Optional[IcmpSummary] = None
    endpoints: List[EndpointEntry] = Field(default_factory=list)
    tls: Optional[TlsSummary] = None
    interest: InterestAnnotations = Field(default_factory=InterestAnnotations)


# ── V1 Analysis Models (kept for backward compatibility) ─────────────────────

class AnalysisIssue(BaseModel):
    """A single issue found by AI analysis (v1 format)."""

    severity: str = Field(..., description="low, medium, high, critical")
    category: str = Field(..., description="retransmissions, latency, errors, dns, etc.")
    description: str
    affected_flows: List[str] = Field(default_factory=list)
    recommendation: str = ""


class AnalysisRequest(BaseModel):
    """Request to run AI analysis on a capture."""

    provider: Optional[str] = Field(None, description="anthropic or openai (uses default if omitted)")
    prompt: str = Field(
        "Analyze this capture for network issues, retransmissions, latency problems, and protocol errors",
        description="Analysis prompt / focus",
    )
    focus: List[str] = Field(
        default_factory=lambda: ["retransmissions", "latency", "errors"],
        description="Areas to focus analysis on",
    )
    pack: Optional[str] = Field(None, description="Analysis pack to use (overrides focus)")


class AnalysisResult(BaseModel):
    """AI analysis results for a capture (v1 format — kept for compat)."""

    capture_id: str
    summary: str
    issues: List[AnalysisIssue] = Field(default_factory=list)
    statistics: Dict[str, Any] = Field(default_factory=dict)
    provider: str = ""
    model: str = ""
    tokens_used: int = 0
    analyzed_at: Optional[str] = None


# ── V2 Analysis Models ──────────────────────────────────────────────────────

class EvidenceCitation(BaseModel):
    """A specific piece of evidence backing a finding."""

    metric: str = Field(..., description="e.g. 'tcp_health.retransmission_pct'")
    value: str = Field(..., description="The observed value, e.g. '3.2%'")
    context: str = Field("", description="Why this value matters")


class Finding(BaseModel):
    """A single finding from AI analysis with evidence."""

    id: str = Field(..., description="Unique finding ID, e.g. 'F1'")
    title: str
    severity: str = Field(..., description="low, medium, high, critical")
    confidence: Confidence
    category: str = Field(..., description="retransmissions, latency, dns, tls, throughput, security")
    description: str
    evidence: List[EvidenceCitation] = Field(default_factory=list)
    affected_flows: List[str] = Field(default_factory=list)
    likely_causes: List[str] = Field(default_factory=list)
    next_steps: List[str] = Field(default_factory=list)
    cross_references: List[str] = Field(default_factory=list, description="IDs of related findings")


class InsufficientEvidenceNote(BaseModel):
    """Areas where analysis was requested but data is insufficient."""

    area: str
    reason: str
    suggestion: str = ""


class AnalysisResultV2(BaseModel):
    """Evidence-based AI analysis result with structured findings."""

    capture_id: str
    pack: str = "custom"
    summary: str
    health_badge: HealthBadge = HealthBadge.INSUFFICIENT
    findings: List[Finding] = Field(default_factory=list)
    insufficient_evidence: List[InsufficientEvidenceNote] = Field(default_factory=list)
    provider: str = ""
    model: str = ""
    tokens_used: int = 0
    analyzed_at: Optional[str] = None

    # V1 compatibility — flatten findings into issues format
    @property
    def issues(self) -> List[AnalysisIssue]:
        """Convert v2 findings to v1 issues for backward compat."""
        return [
            AnalysisIssue(
                severity=f.severity,
                category=f.category,
                description=f.description,
                affected_flows=f.affected_flows,
                recommendation="; ".join(f.next_steps) if f.next_steps else "",
            )
            for f in self.findings
        ]

    @property
    def statistics(self) -> Dict[str, Any]:
        return {
            "findings_count": len(self.findings),
            "health_badge": self.health_badge,
            "confidence_distribution": {
                c.value: sum(1 for f in self.findings if f.confidence == c)
                for c in Confidence
            },
        }
