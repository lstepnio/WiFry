"""Analysis pack definitions for capture v2.

Each pack bundles a BPF filter, default duration, tshark queries to run,
focus areas for AI analysis, and threshold rules for interest detection.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AnalysisPack(str, Enum):
    """Pre-defined capture + analysis modes."""

    CONNECTIVITY = "connectivity"
    DNS = "dns"
    HTTPS = "https"
    STREAMING = "streaming"
    SECURITY = "security"
    CUSTOM = "custom"


class ThresholdRule(BaseModel):
    """A single threshold rule for interest detection."""

    metric: str = Field(..., description="Metric path, e.g. 'tcp_health.retransmission_pct'")
    operator: str = Field(..., description="gt, lt, gte, lte, eq")
    value: float
    severity: str = Field("medium", description="low, medium, high, critical")
    label: str = Field(..., description="Human-readable label for this anomaly")


class PackConfig(BaseModel):
    """Configuration for a single analysis pack."""

    id: AnalysisPack
    name: str
    description: str
    icon: str = ""
    color: str = ""
    bpf: str = Field("", description="Default BPF filter (empty = all traffic)")
    default_duration_secs: int = 60
    max_duration_secs: int = 300
    queries: List[str] = Field(
        default_factory=list,
        description="Which tshark stat extractions to run: protocol, tcp, io, expert, dns, throughput, icmp, endpoints, tls",
    )
    focus_areas: List[str] = Field(default_factory=list, description="AI focus areas")
    thresholds: List[ThresholdRule] = Field(default_factory=list)


# ── Pack definitions ─────────────────────────────────────────────────────────

PACK_CONFIGS: Dict[AnalysisPack, PackConfig] = {
    AnalysisPack.CONNECTIVITY: PackConfig(
        id=AnalysisPack.CONNECTIVITY,
        name="Connectivity Check",
        description="General network health — retransmissions, latency, packet loss, ICMP reachability",
        icon="wifi",
        color="blue",
        bpf="",
        default_duration_secs=30,
        max_duration_secs=120,
        queries=["protocol", "tcp", "io", "expert", "icmp", "endpoints"],
        focus_areas=["retransmissions", "latency", "packet_loss", "reachability"],
        thresholds=[
            ThresholdRule(metric="tcp_health.retransmission_pct", operator="gt", value=2.0, severity="high", label="High TCP retransmission rate"),
            ThresholdRule(metric="tcp_health.retransmission_pct", operator="gt", value=0.5, severity="medium", label="Elevated TCP retransmission rate"),
            ThresholdRule(metric="tcp_health.zero_window_count", operator="gt", value=5, severity="high", label="TCP zero window events"),
            ThresholdRule(metric="tcp_health.rst_count", operator="gt", value=10, severity="medium", label="Connection resets detected"),
            ThresholdRule(metric="icmp.unreachable_count", operator="gt", value=0, severity="high", label="ICMP unreachable messages"),
        ],
    ),
    AnalysisPack.DNS: PackConfig(
        id=AnalysisPack.DNS,
        name="DNS Deep Dive",
        description="DNS resolution health — query latency, NXDOMAIN, SERVFAIL, query patterns",
        icon="globe",
        color="green",
        bpf="port 53",
        default_duration_secs=30,
        max_duration_secs=120,
        queries=["protocol", "dns", "io", "expert", "endpoints"],
        focus_areas=["dns_latency", "dns_errors", "query_patterns", "ttl_analysis"],
        thresholds=[
            ThresholdRule(metric="dns.nxdomain_count", operator="gt", value=5, severity="medium", label="Frequent NXDOMAIN responses"),
            ThresholdRule(metric="dns.servfail_count", operator="gt", value=0, severity="high", label="DNS SERVFAIL responses"),
            ThresholdRule(metric="dns.avg_latency_ms", operator="gt", value=200, severity="high", label="High DNS latency"),
            ThresholdRule(metric="dns.avg_latency_ms", operator="gt", value=100, severity="medium", label="Elevated DNS latency"),
            ThresholdRule(metric="dns.timeout_count", operator="gt", value=0, severity="high", label="DNS query timeouts"),
        ],
    ),
    AnalysisPack.HTTPS: PackConfig(
        id=AnalysisPack.HTTPS,
        name="HTTPS / Web",
        description="TLS handshake health, connection setup times, certificate issues",
        icon="lock",
        color="purple",
        bpf="tcp port 443",
        default_duration_secs=60,
        max_duration_secs=300,
        queries=["protocol", "tcp", "io", "expert", "tls", "endpoints"],
        focus_areas=["tls_handshake", "connection_setup", "certificate_errors", "throughput"],
        thresholds=[
            ThresholdRule(metric="tls.handshake_failure_count", operator="gt", value=0, severity="high", label="TLS handshake failures"),
            ThresholdRule(metric="tcp_health.retransmission_pct", operator="gt", value=1.0, severity="medium", label="Retransmissions on HTTPS flows"),
            ThresholdRule(metric="tls.avg_handshake_ms", operator="gt", value=500, severity="high", label="Slow TLS handshakes"),
            ThresholdRule(metric="tls.avg_handshake_ms", operator="gt", value=200, severity="medium", label="Elevated TLS handshake time"),
        ],
    ),
    AnalysisPack.STREAMING: PackConfig(
        id=AnalysisPack.STREAMING,
        name="Streaming / Video",
        description="Throughput stability, buffering indicators, ABR bitrate switching",
        icon="play",
        color="red",
        bpf="tcp port 443 or tcp port 80",
        default_duration_secs=120,
        max_duration_secs=600,
        queries=["protocol", "tcp", "io", "expert", "throughput", "endpoints", "tls"],
        focus_areas=["throughput_stability", "buffering", "retransmissions", "flow_analysis"],
        thresholds=[
            ThresholdRule(metric="throughput.coefficient_of_variation", operator="gt", value=0.5, severity="high", label="Highly variable throughput"),
            ThresholdRule(metric="throughput.coefficient_of_variation", operator="gt", value=0.3, severity="medium", label="Throughput instability"),
            ThresholdRule(metric="tcp_health.retransmission_pct", operator="gt", value=1.0, severity="high", label="Retransmissions affecting streaming"),
            ThresholdRule(metric="throughput.min_bps", operator="lt", value=500000, severity="medium", label="Throughput dip below 500 Kbps"),
        ],
    ),
    AnalysisPack.SECURITY: PackConfig(
        id=AnalysisPack.SECURITY,
        name="Security Audit",
        description="Unusual traffic patterns, unencrypted flows, port scans, suspicious destinations",
        icon="shield",
        color="amber",
        bpf="",
        default_duration_secs=60,
        max_duration_secs=300,
        queries=["protocol", "tcp", "io", "expert", "dns", "endpoints", "tls"],
        focus_areas=["unencrypted_traffic", "unusual_ports", "scan_patterns", "suspicious_destinations"],
        thresholds=[
            ThresholdRule(metric="protocol_breakdown.unencrypted_pct", operator="gt", value=20, severity="medium", label="Significant unencrypted traffic"),
            ThresholdRule(metric="endpoints.unique_dst_count", operator="gt", value=50, severity="medium", label="Many unique destinations"),
            ThresholdRule(metric="tcp_health.rst_count", operator="gt", value=20, severity="medium", label="Many connection resets (scan indicator)"),
        ],
    ),
    AnalysisPack.CUSTOM: PackConfig(
        id=AnalysisPack.CUSTOM,
        name="Custom Capture",
        description="Full control — set your own BPF filter, duration, and analysis focus",
        icon="settings",
        color="gray",
        bpf="",
        default_duration_secs=60,
        max_duration_secs=3600,
        queries=["protocol", "tcp", "io", "expert", "dns", "throughput", "endpoints"],
        focus_areas=["retransmissions", "latency", "errors", "throughput"],
        thresholds=[
            ThresholdRule(metric="tcp_health.retransmission_pct", operator="gt", value=2.0, severity="high", label="High retransmission rate"),
            ThresholdRule(metric="tcp_health.retransmission_pct", operator="gt", value=0.5, severity="medium", label="Elevated retransmission rate"),
        ],
    ),
}


def get_pack_config(pack: AnalysisPack) -> PackConfig:
    """Get pack configuration by ID."""
    return PACK_CONFIGS[pack]


def list_packs() -> List[PackConfig]:
    """List all available pack configurations."""
    return list(PACK_CONFIGS.values())
