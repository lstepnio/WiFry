"""Pydantic models for test sessions and support bundles.

A TestSession is the top-level correlation container that groups all
artifacts generated during a testing activity. Every capture, logcat,
screenshot, analysis, stream recording, etc. is linked to a session
via its session_id.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ArtifactType(str, Enum):
    CAPTURE = "capture"           # Packet capture (.pcap)
    ANALYSIS = "analysis"         # AI analysis result
    LOGCAT = "logcat"             # ADB logcat session
    SCREENSHOT = "screenshot"     # ADB or HDMI screenshot
    BUGREPORT = "bugreport"       # ADB bugreport
    HDMI_FRAME = "hdmi_frame"     # HDMI capture frame
    HDMI_RECORDING = "hdmi_recording"  # HDMI video recording
    STREAM_SESSION = "stream"     # HLS/DASH stream session
    SPEED_TEST = "speed_test"     # iperf3 result
    WIFI_SCAN = "wifi_scan"       # WiFi environment scan
    SHELL_OUTPUT = "shell_output" # ADB shell command output
    REPORT = "report"             # Generated test report
    NOTE = "note"                 # User annotation / note
    SEGMENT = "segment"           # Saved video segment
    PROBE = "probe"               # Video quality probe result
    IMPAIRMENT_LOG = "impairment_log"  # Record of impairment applied


class Artifact(BaseModel):
    """A single artifact linked to a session."""

    id: str
    session_id: str
    type: ArtifactType
    name: str = ""
    description: str = ""
    file_path: Optional[str] = None
    data: Optional[Dict[str, Any]] = None  # Inline data (for small artifacts like notes, configs)
    tags: List[str] = Field(default_factory=list)
    created_at: str = ""
    size_bytes: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DeviceInfo(BaseModel):
    """STB/device info snapshot at session creation."""

    serial: str = ""
    model: str = ""
    manufacturer: str = ""
    android_version: str = ""
    ip_address: str = ""
    mac_address: str = ""
    firmware: str = ""
    custom: Dict[str, str] = Field(default_factory=dict)


class ImpairmentSnapshot(BaseModel):
    """Record of impairment settings at a point in time."""

    timestamp: str
    profile_name: str = ""
    network_config: Optional[Dict[str, Any]] = None
    wifi_config: Optional[Dict[str, Any]] = None
    label: str = ""


class TestSession(BaseModel):
    """Top-level test session grouping all correlated artifacts."""

    id: str
    name: str
    description: str = ""
    status: SessionStatus = SessionStatus.ACTIVE
    tags: List[str] = Field(default_factory=list)
    notes: str = ""

    # Device under test
    device: DeviceInfo = Field(default_factory=DeviceInfo)

    # Environment
    network_interface: str = ""
    ap_ssid: str = ""
    ap_channel: int = 0

    # Timeline
    created_at: str = ""
    updated_at: str = ""
    completed_at: str = ""

    # Impairment history during this session
    impairment_log: List[ImpairmentSnapshot] = Field(default_factory=list)

    # Artifact references (IDs)
    artifact_ids: List[str] = Field(default_factory=list)

    # Summary stats
    artifact_count: int = 0
    total_size_bytes: int = 0


class SessionSummary(BaseModel):
    """Compact session listing."""

    id: str
    name: str
    status: SessionStatus
    device_model: str = ""
    device_ip: str = ""
    tags: List[str] = Field(default_factory=list)
    artifact_count: int = 0
    created_at: str = ""
    updated_at: str = ""


class CreateSessionRequest(BaseModel):
    """Request to create a new test session."""

    name: str = Field(..., min_length=1)
    description: str = ""
    tags: List[str] = Field(default_factory=list)
    device_serial: str = Field("", description="ADB serial to auto-populate device info")
    network_interface: str = "wlan0"


class ActiveSessionState(BaseModel):
    """Durable pointer to the session used for auto-linking."""

    active_session_id: Optional[str] = None


class ActiveSessionResponse(BaseModel):
    """API response for the current active session."""

    active_session_id: Optional[str] = None
    session_name: Optional[str] = None


class SupportBundle(BaseModel):
    """A packaged support bundle for sharing."""

    session_id: str
    session_name: str
    bundle_path: str = ""
    size_bytes: int = 0
    artifact_count: int = 0
    created_at: str = ""

    # Metadata included in the bundle
    device: DeviceInfo = Field(default_factory=DeviceInfo)
    tags: List[str] = Field(default_factory=list)
    notes: str = ""
    impairment_log: List[ImpairmentSnapshot] = Field(default_factory=list)
