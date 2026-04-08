"""EXPERIMENTAL_VIDEO_CAPTURE — UVC device discovery and management.

Handles device enumeration, health monitoring, and reconnection with
exponential backoff. Tolerates USB disconnect/reconnect and device
index changes by matching on device name rather than path.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger("wifry.experimental.video_capture")

# EXPERIMENTAL_VIDEO_CAPTURE — Known UVC capture device identifiers
_KNOWN_CAPTURE_DEVICES = [
    "cam link 4k",
    "cam link",
    "elgato",
    "usb video",
    "hdmi capture",
    "video capture",
]

_BACKOFF_BASE = 2.0
_BACKOFF_MAX = 60.0
_BACKOFF_ATTEMPTS_RESET = 5


class DeviceState(str, Enum):
    """EXPERIMENTAL_VIDEO_CAPTURE — Device lifecycle states."""
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    STREAMING = "streaming"
    ERROR = "error"


@dataclass
class DeviceInfo:
    """EXPERIMENTAL_VIDEO_CAPTURE — Current device state snapshot."""
    state: DeviceState = DeviceState.DISCONNECTED
    path: Optional[str] = None
    name: Optional[str] = None
    last_seen: Optional[float] = None
    error: Optional[str] = None
    reconnect_attempts: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "path": self.path,
            "name": self.name,
            "last_seen": self.last_seen,
            "error": self.error,
            "reconnect_attempts": self.reconnect_attempts,
        }


# EXPERIMENTAL_VIDEO_CAPTURE — Module-level singleton
_device = DeviceInfo()


def get_device_info() -> DeviceInfo:
    """Return the current device state (read-only snapshot)."""
    return _device


async def discover_device() -> Optional[str]:
    """EXPERIMENTAL_VIDEO_CAPTURE — Find a UVC capture device by name.

    Scans /sys/class/video4linux/ and matches against known capture
    device names. Returns the /dev/videoN path or None.
    """
    v4l_dir = Path("/sys/class/video4linux")
    if not v4l_dir.exists():
        return None

    for entry in sorted(v4l_dir.iterdir()):
        name_file = entry / "name"
        if not name_file.exists():
            continue
        try:
            dev_name = name_file.read_text().strip().lower()
        except OSError:
            continue

        for known in _KNOWN_CAPTURE_DEVICES:
            if known in dev_name:
                dev_path = f"/dev/{entry.name}"
                if Path(dev_path).exists():
                    logger.info(
                        "[EXPERIMENTAL_VIDEO_CAPTURE] Found device: %s at %s",
                        dev_name, dev_path,
                    )
                    return dev_path
    return None


async def discover_device_mock() -> Optional[str]:
    """EXPERIMENTAL_VIDEO_CAPTURE — Mock device discovery for dev/CI."""
    logger.info("[EXPERIMENTAL_VIDEO_CAPTURE] Mock mode: returning fake /dev/video0")
    return "/dev/video0"


async def probe_device(path: str) -> bool:
    """EXPERIMENTAL_VIDEO_CAPTURE — Check if a device path is still valid."""
    return Path(path).exists() and Path(path).is_char_device()


async def update_device_state(
    state: DeviceState,
    path: Optional[str] = None,
    name: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """EXPERIMENTAL_VIDEO_CAPTURE — Thread-safe device state update."""
    async with _device._lock:
        _device.state = state
        if path is not None:
            _device.path = path
        if name is not None:
            _device.name = name
        if error is not None:
            _device.error = error
        elif state in (DeviceState.CONNECTED, DeviceState.STREAMING):
            _device.error = None
        if state == DeviceState.CONNECTED:
            _device.last_seen = time.time()
            _device.reconnect_attempts = 0


def backoff_delay() -> float:
    """EXPERIMENTAL_VIDEO_CAPTURE — Exponential backoff for reconnection."""
    delay = min(
        _BACKOFF_BASE ** min(_device.reconnect_attempts, _BACKOFF_ATTEMPTS_RESET),
        _BACKOFF_MAX,
    )
    _device.reconnect_attempts += 1
    return delay
