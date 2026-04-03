"""Pydantic models for packet capture and AI analysis."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CaptureStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    ERROR = "error"


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


class StartCaptureRequest(BaseModel):
    """Request to start a new packet capture."""

    interface: str = Field(..., description="Network interface to capture on")
    name: str = Field("", description="Human-readable name for this capture")
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
    filters: CaptureFilters
    bpf_expression: str = ""
    started_at: Optional[str] = None
    stopped_at: Optional[str] = None
    packet_count: int = 0
    file_size_bytes: int = 0
    pcap_path: str = ""
    error: Optional[str] = None


class AnalysisIssue(BaseModel):
    """A single issue found by AI analysis."""

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


class AnalysisResult(BaseModel):
    """AI analysis results for a capture."""

    capture_id: str
    summary: str
    issues: List[AnalysisIssue] = Field(default_factory=list)
    statistics: Dict[str, Any] = Field(default_factory=dict)
    provider: str = ""
    model: str = ""
    tokens_used: int = 0
    analyzed_at: Optional[str] = None
