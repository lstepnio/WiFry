"""Pydantic models for automated test scenarios."""

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from .impairment import ImpairmentConfig


class ScenarioStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    ERROR = "error"


class ScenarioStep(BaseModel):
    """A single step in a test scenario."""

    label: str = ""
    profile: Optional[str] = Field(None, description="Named profile to apply")
    impairment: Optional[ImpairmentConfig] = Field(None, description="Inline impairment config")
    duration_secs: int = Field(60, ge=1, le=7200)

    # Optional actions at step start
    start_capture: bool = False
    start_logcat: bool = False
    take_screenshot: bool = False


class ScenarioDefinition(BaseModel):
    """A reusable test scenario definition."""

    id: str = ""
    name: str = Field(..., min_length=1)
    description: str = ""
    interface: str = "wlan0"
    adb_serial: str = Field("", description="ADB device serial for logcat/screenshots")
    repeat: int = Field(1, ge=1, le=100)
    steps: List[ScenarioStep] = Field(..., min_length=1)


class ScenarioStepResult(BaseModel):
    """Result of executing a single step."""

    step_index: int
    label: str
    started_at: str
    completed_at: str
    profile_applied: str = ""
    capture_id: Optional[str] = None
    logcat_session_id: Optional[str] = None
    screenshot_path: Optional[str] = None


class ScenarioRun(BaseModel):
    """State of a running or completed scenario."""

    id: str
    scenario_id: str
    scenario_name: str
    status: ScenarioStatus = ScenarioStatus.IDLE
    current_step: int = 0
    total_steps: int = 0
    current_repeat: int = 1
    total_repeats: int = 1
    started_at: str = ""
    completed_at: str = ""
    step_results: List[ScenarioStepResult] = Field(default_factory=list)
    error: Optional[str] = None
