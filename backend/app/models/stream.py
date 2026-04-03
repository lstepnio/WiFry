"""Pydantic models for ABR stream analysis (HLS + DASH)."""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class StreamType(str, Enum):
    HLS = "hls"
    DASH = "dash"
    UNKNOWN = "unknown"


class VariantInfo(BaseModel):
    """A variant/representation in an ABR manifest."""

    bandwidth: int = Field(..., description="Declared bandwidth in bps")
    resolution: str = Field("", description="e.g. '1920x1080'")
    codecs: str = Field("", description="e.g. 'avc1.64001f,mp4a.40.2'")
    url: str = Field("", description="Playlist/representation URL")
    frame_rate: Optional[float] = None


class SegmentInfo(BaseModel):
    """A single downloaded media segment."""

    url: str
    sequence: int = 0
    duration_secs: float = Field(0, description="Expected duration from manifest")
    download_time_secs: float = Field(0, description="Actual download time")
    size_bytes: int = 0
    bitrate_bps: int = Field(0, description="Declared bitrate from active variant")
    throughput_bps: int = Field(0, description="Actual throughput (size / download_time)")
    timestamp: str = ""
    status_code: int = 200
    saved_path: Optional[str] = None


class BitrateSwitch(BaseModel):
    """Record of a bitrate change."""

    timestamp: str
    from_bandwidth: int
    to_bandwidth: int
    from_resolution: str = ""
    to_resolution: str = ""


class StreamSession(BaseModel):
    """An active or recent ABR stream session."""

    id: str
    stream_type: StreamType = StreamType.UNKNOWN
    client_ip: str = ""
    master_url: str = ""
    variants: List[VariantInfo] = Field(default_factory=list)
    active_variant: Optional[VariantInfo] = None
    segments: List[SegmentInfo] = Field(default_factory=list, description="Recent segments (rolling window)")
    bitrate_switches_log: List[BitrateSwitch] = Field(default_factory=list)
    started_at: str = ""
    last_activity: str = ""
    active: bool = True

    # Computed metrics
    current_bitrate_bps: int = 0
    avg_throughput_bps: int = 0
    buffer_health_secs: float = Field(0, description="Estimated buffer level in seconds")
    bitrate_switches: int = 0
    segment_errors: int = 0
    rebuffer_events: int = 0
    throughput_ratio: float = Field(0, description="actual / required (≥1.33 for stability)")
    total_segments: int = 0


class StreamSessionSummary(BaseModel):
    """Compact summary for listing streams."""

    id: str
    stream_type: StreamType
    client_ip: str
    active: bool
    current_bitrate_bps: int
    resolution: str
    buffer_health_secs: float
    throughput_ratio: float
    bitrate_switches: int
    segment_errors: int
    total_segments: int
    started_at: str
    last_activity: str


class StreamEvent(BaseModel):
    """Event sent from mitmproxy addon to WiFry backend."""

    event_type: str = Field(..., description="manifest | segment | error")
    client_ip: str = ""
    url: str = ""
    content_type: str = ""
    status_code: int = 200
    request_time_secs: float = 0
    response_size_bytes: int = 0
    body: Optional[str] = Field(None, description="Manifest body (for manifest events)")
    headers: Dict[str, str] = Field(default_factory=dict)


class ProxyStatus(BaseModel):
    """Current proxy state."""

    enabled: bool = False
    running: bool = False
    port: int = 8888
    save_segments: bool = False
    max_storage_mb: int = 500
    cert_installed_hint: str = ""
    intercepted_flows: int = 0


class ProxySettings(BaseModel):
    """Configurable proxy settings."""

    save_segments: bool = False
    max_storage_mb: int = 500
