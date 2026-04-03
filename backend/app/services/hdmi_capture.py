"""HDMI capture via Elgato Cam Link 4K (or compatible USB capture devices).

Uses v4l2 (Video4Linux2) + ffmpeg to capture HDMI input from STBs.
The Elgato Cam Link 4K appears as a standard UVC device on Linux.

Capabilities:
  - Live HDMI frame capture (screenshot of what's on the STB screen)
  - Video recording of HDMI output
  - Frame comparison (visual regression)
  - Feed to video quality probe for codec-independent quality analysis
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..config import settings
from ..utils.shell import run

logger = logging.getLogger(__name__)

CAPTURE_DIR = Path("/var/lib/wifry/hdmi-captures") if not settings.mock_mode else Path("/tmp/wifry-hdmi")

_recording_processes: Dict[str, asyncio.subprocess.Process] = {}
_recordings: Dict[str, dict] = {}


def _ensure_dir() -> Path:
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    return CAPTURE_DIR


async def detect_devices() -> List[dict]:
    """Detect connected USB capture devices (Cam Link 4K, etc.)."""
    if settings.mock_mode:
        return [
            {
                "device": "/dev/video0",
                "name": "Elgato Cam Link 4K",
                "capabilities": "1920x1080@60fps",
                "connected": True,
            }
        ]

    result = await run("v4l2-ctl", "--list-devices", check=False)
    if not result.success:
        return []

    devices = []
    current_name = ""
    for line in result.stdout.splitlines():
        line = line.strip()
        if line and not line.startswith("/"):
            current_name = line.rstrip(":")
        elif line.startswith("/dev/video"):
            # Check if it's a capture device
            caps = await run("v4l2-ctl", "-d", line, "--all", check=False)
            if caps.success and "Video Capture" in caps.stdout:
                device_info = {
                    "device": line,
                    "name": current_name,
                    "capabilities": "",
                    "connected": True,
                }
                # Get supported formats
                fmts = await run("v4l2-ctl", "-d", line, "--list-formats-ext", check=False)
                if fmts.success:
                    if "1920x1080" in fmts.stdout:
                        device_info["capabilities"] = "1920x1080"
                    elif "3840x2160" in fmts.stdout:
                        device_info["capabilities"] = "3840x2160"
                devices.append(device_info)

    return devices


async def capture_frame(device: str = "/dev/video0", resolution: str = "1920x1080") -> str:
    """Capture a single frame from HDMI input. Returns path to PNG."""
    d = _ensure_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = d / f"hdmi_frame_{ts}.png"

    if settings.mock_mode:
        output.write_bytes(b"MOCK HDMI FRAME PNG")
        return str(output)

    result = await run(
        "ffmpeg", "-y",
        "-f", "v4l2",
        "-video_size", resolution,
        "-i", device,
        "-frames:v", "1",
        str(output),
        check=False, timeout=10,
    )

    if not result.success:
        raise RuntimeError(f"Frame capture failed: {result.stderr[:200]}")

    return str(output)


async def start_recording(
    device: str = "/dev/video0",
    resolution: str = "1920x1080",
    max_duration_secs: int = 300,
) -> dict:
    """Start recording HDMI input. Returns recording info."""
    rec_id = uuid.uuid4().hex[:10]
    d = _ensure_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = d / f"hdmi_rec_{ts}.mp4"
    now = datetime.now(timezone.utc).isoformat()

    recording = {
        "id": rec_id,
        "device": device,
        "output": str(output),
        "resolution": resolution,
        "started_at": now,
        "status": "recording",
        "duration_secs": 0,
    }

    if settings.mock_mode:
        recording["status"] = "recording"
        _recordings[rec_id] = recording
        return recording

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y",
        "-f", "v4l2",
        "-video_size", resolution,
        "-framerate", "30",
        "-i", device,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-t", str(max_duration_secs),
        str(output),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    _recording_processes[rec_id] = proc
    _recordings[rec_id] = recording

    # Monitor in background
    asyncio.create_task(_monitor_recording(rec_id, proc))

    logger.info("HDMI recording started: %s -> %s", device, output)
    return recording


async def stop_recording(rec_id: str) -> dict:
    """Stop a recording."""
    proc = _recording_processes.get(rec_id)
    if proc and proc.returncode is None:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()

    rec = _recordings.get(rec_id, {})
    rec["status"] = "stopped"
    return rec


async def _monitor_recording(rec_id: str, proc: asyncio.subprocess.Process) -> None:
    try:
        await proc.communicate()
        rec = _recordings.get(rec_id, {})
        rec["status"] = "completed" if proc.returncode == 0 else "error"
    except Exception as e:
        logger.error("Recording %s error: %s", rec_id, e)
    finally:
        _recording_processes.pop(rec_id, None)


def list_recordings() -> List[dict]:
    return sorted(_recordings.values(), key=lambda r: r.get("started_at", ""), reverse=True)


def list_frames() -> List[dict]:
    """List captured HDMI frames."""
    d = _ensure_dir()
    frames = []
    for f in sorted(d.glob("hdmi_frame_*.png"), reverse=True):
        frames.append({
            "filename": f.name,
            "path": str(f),
            "size_bytes": f.stat().st_size,
            "created_at": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
        })
    return frames
