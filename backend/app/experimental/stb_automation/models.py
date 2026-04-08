"""STB_AUTOMATION — Pydantic models for STB test automation.

All models used by the stb_automation module are defined here so they
can be imported without pulling in service-layer dependencies.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel


# --- UI Elements ---


class UIElement(BaseModel):
    """A single node from the Android UI hierarchy."""

    resource_id: str = ""
    text: str = ""
    class_name: str = ""
    package: str = ""
    content_desc: str = ""
    bounds: str = ""
    focused: bool = False
    clickable: bool = False
    selected: bool = False


# --- Logcat Events ---


class LogcatEvent(BaseModel):
    """Parsed high-level event from a logcat stream."""

    event_type: str = ""  # ACTIVITY_DISPLAYED, ACTIVITY_RESUMED, FOCUS_CHANGED, ...
    package: str = ""
    activity: str = ""
    detail: str = ""
    timestamp: str = ""
    raw: str = ""


# --- Screen State ---


class ScreenState(BaseModel):
    """Raw observation from a single ADB read cycle."""

    package: str = ""
    activity: str = ""
    ui_elements: List[UIElement] = []
    focused_element: Optional[UIElement] = None
    focused_context: str = ""  # human-readable context from all signals
    window_title: str = ""  # from dumpsys window
    fragments: List[str] = []  # active fragment names from dumpsys activity top
    recent_events: List[LogcatEvent] = []
    timestamp: str = ""


# --- Navigation Model ---


class ScreenNode(BaseModel):
    """Persistent node in the navigation graph."""

    id: str  # 12-char hex fingerprint
    fingerprint: str
    screen_type: str = "unknown"
    title: str = ""
    package: str = ""
    activity: str = ""
    elements: List[UIElement] = []
    vision_analysis: Optional[dict] = None
    visit_count: int = 0
    last_visited: str = ""


class TransitionEdge(BaseModel):
    """Directed edge between two screen nodes."""

    from_node: str
    to_node: str
    action: str  # keycode name
    success_count: int = 0
    no_effect_count: int = 0
    avg_transition_ms: float = 0.0
    settle_method: str = ""  # logcat, dumpsys, uiautomator, timeout


class NavigationModel(BaseModel):
    """Persistent navigation graph for a device."""

    device_id: str
    device_model: str = ""
    created_at: str = ""
    updated_at: str = ""
    home_node_id: str = ""
    nodes: Dict[str, ScreenNode] = {}
    edges: List[TransitionEdge] = []


# --- Crawl ---


class CrawlConfig(BaseModel):
    """Configuration for a BFS crawl session."""

    serial: str
    max_depth: int = 5
    max_transitions: int = 200
    settle_timeout_ms: int = 3000
    enable_vision_fallback: bool = True
    enable_logcat_monitor: bool = True
    logcat_tags: List[str] = ["ActivityManager:I", "WindowManager:I"]
    explore_actions: List[str] = [
        "up",
        "down",
        "left",
        "right",
        "enter",
        "back",
    ]


class CrawlStatus(BaseModel):
    """Live status of a crawl session."""

    state: str = "idle"  # idle, running, paused, completed, error
    current_node_id: Optional[str] = None
    nodes_discovered: int = 0
    transitions_executed: int = 0
    error: Optional[str] = None


# --- Anomaly Detection ---


class AnomalyPattern(BaseModel):
    """Configurable logcat error pattern."""

    name: str
    pattern: str  # regex applied to logcat message
    tags: List[str] = []  # logcat tags to match (empty = all)
    severity: str = "medium"  # critical, high, medium, low
    category: str = ""  # crash, media, network, memory, permission


class DetectedAnomaly(BaseModel):
    """A single anomaly detected during execution."""

    pattern_name: str
    severity: str
    category: str
    timestamp: str
    logcat_line: Optional[LogcatEvent] = None
    vision_state: Optional[str] = None
    context_lines: List[str] = []
    diagnostics_collected: bool = False
    artifact_ids: List[str] = []


# --- Test Flows ---


class TestStep(BaseModel):
    """Single step in a test flow."""

    action: str  # keycode or "wait" or "assert"
    expected_screen_id: Optional[str] = None
    expected_activity: Optional[str] = None
    wait_ms: int = 0
    description: str = ""
    collect_diagnostics: bool = False


class TestFlow(BaseModel):
    """Editable sequence of test steps."""

    id: str
    name: str
    description: str = ""
    serial: str
    steps: List[TestStep] = []
    created_at: str = ""
    updated_at: str = ""
    source: str = "manual"  # manual, recorded, chaos, nl_generated


class TestFlowRun(BaseModel):
    """Live status of a test flow execution."""

    flow_id: str
    state: str = "idle"  # idle, running, paused, completed, failed, error
    current_step: int = 0
    steps_passed: int = 0
    steps_failed: int = 0
    anomalies_detected: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None


# --- Chaos Mode ---


class ChaosConfig(BaseModel):
    """Configuration for a chaos exploration session."""

    serial: str
    duration_secs: int = 300
    seed: Optional[int] = None
    key_weights: Dict[str, float] = {}
    on_anomaly: str = "collect"  # stop, collect, ignore
    enable_vision_checks: bool = False
    vision_check_interval_secs: int = 30


class ChaosResult(BaseModel):
    """Results from a chaos exploration session."""

    state: str = "idle"
    duration_secs: float = 0
    keys_sent: int = 0
    screens_visited: int = 0
    anomalies: List[DetectedAnomaly] = []
    seed_used: int = 0
