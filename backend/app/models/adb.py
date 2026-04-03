"""Pydantic models for ADB device management."""

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class AdbDeviceState(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    OFFLINE = "offline"
    UNAUTHORIZED = "unauthorized"


class AdbDevice(BaseModel):
    """An ADB-connected device."""

    serial: str = Field(..., description="Device serial (e.g. '192.168.4.10:5555')")
    state: AdbDeviceState = AdbDeviceState.DISCONNECTED
    model: str = ""
    product: str = ""
    transport_id: str = ""

    # Device info (populated after connect)
    manufacturer: str = ""
    android_version: str = ""
    sdk_version: str = ""
    display_resolution: str = ""


class AdbConnectRequest(BaseModel):
    """Request to connect to a device over network ADB."""

    ip: str = Field(..., description="Device IP address")
    port: int = Field(5555, ge=1, le=65535, description="ADB port")


class AdbShellRequest(BaseModel):
    """Request to execute a shell command."""

    serial: str
    command: str = Field(..., min_length=1, max_length=2000)
    timeout: int = Field(30, ge=1, le=300)


class AdbShellResult(BaseModel):
    """Result of a shell command."""

    serial: str
    command: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0


class AdbFileRequest(BaseModel):
    """Request for file push/pull."""

    serial: str
    remote_path: str
    local_path: str = ""  # auto-generated for pulls


class AdbKeyEvent(BaseModel):
    """Request to send a key event."""

    serial: str
    keycode: str = Field(..., description="Android keycode name or number (e.g. 'KEYCODE_HOME', '3')")


class AdbInstallRequest(BaseModel):
    """Request to install an APK."""

    serial: str
    apk_path: str


class LogcatSession(BaseModel):
    """An active logcat streaming session."""

    id: str
    serial: str
    filters: List[str] = Field(default_factory=list, description="Logcat filter specs (e.g. 'ActivityManager:I')")
    active: bool = True
    started_at: str = ""
    line_count: int = 0
    scenario_id: Optional[str] = Field(None, description="Associated scenario ID for correlated logging")


class LogcatLine(BaseModel):
    """A single logcat line."""

    timestamp: str = ""
    pid: str = ""
    tid: str = ""
    level: str = ""  # V, D, I, W, E, F
    tag: str = ""
    message: str = ""
    raw: str = ""


# Common Android keycodes for STB remote control
STB_KEYCODES = {
    "home": "KEYCODE_HOME",
    "back": "KEYCODE_BACK",
    "up": "KEYCODE_DPAD_UP",
    "down": "KEYCODE_DPAD_DOWN",
    "left": "KEYCODE_DPAD_LEFT",
    "right": "KEYCODE_DPAD_RIGHT",
    "enter": "KEYCODE_DPAD_CENTER",
    "menu": "KEYCODE_MENU",
    "play_pause": "KEYCODE_MEDIA_PLAY_PAUSE",
    "stop": "KEYCODE_MEDIA_STOP",
    "rewind": "KEYCODE_MEDIA_REWIND",
    "fast_forward": "KEYCODE_MEDIA_FAST_FORWARD",
    "channel_up": "KEYCODE_CHANNEL_UP",
    "channel_down": "KEYCODE_CHANNEL_DOWN",
    "volume_up": "KEYCODE_VOLUME_UP",
    "volume_down": "KEYCODE_VOLUME_DOWN",
    "mute": "KEYCODE_VOLUME_MUTE",
    "power": "KEYCODE_POWER",
    "guide": "KEYCODE_GUIDE",
    "info": "KEYCODE_INFO",
}
