"""ADB device management service.

Manages network ADB connections, shell commands, logcat streaming,
file operations, and key events for Android-based STBs.
"""

import asyncio
import logging
import re
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional

from ..config import settings
from ..models.adb import (
    AdbDevice,
    AdbDeviceState,
    AdbShellResult,
    LogcatLine,
    LogcatSession,
)
from ..utils.shell import CommandResult, run

logger = logging.getLogger(__name__)

# In-memory registries
_devices: Dict[str, AdbDevice] = {}
_logcat_sessions: Dict[str, LogcatSession] = {}
_logcat_processes: Dict[str, asyncio.subprocess.Process] = {}
_logcat_buffers: Dict[str, Deque[LogcatLine]] = {}

MAX_LOGCAT_LINES = 5000
FILE_STORE = Path("/var/lib/wifry/adb-files")
_lock = asyncio.Lock()


async def _adb(*args: str, timeout: float = 30) -> CommandResult:
    """Run an adb command."""
    if settings.mock_mode:
        from ..utils.shell import MockShell
        mock = MockShell()
        return await mock.run("adb", *args, timeout=timeout)
    return await run("adb", *args, timeout=timeout, check=False)


# --- Device management ---

async def connect(ip: str, port: int = 5555) -> AdbDevice:
    """Connect to a device over network ADB."""
    serial = f"{ip}:{port}"

    if settings.mock_mode:
        device = _mock_device(serial)
        async with _lock:
            _devices[serial] = device
        return device

    result = await _adb("connect", serial)
    if "connected" in result.stdout.lower():
        device = AdbDevice(serial=serial, state=AdbDeviceState.CONNECTED)
        # Fetch device info
        await _populate_device_info(device)
        async with _lock:
            _devices[serial] = device
        logger.info("Connected to %s", serial)
        return device

    state = AdbDeviceState.UNAUTHORIZED if "unauthorized" in result.stdout.lower() else AdbDeviceState.DISCONNECTED
    device = AdbDevice(serial=serial, state=state)
    async with _lock:
        _devices[serial] = device
    logger.warning("Failed to connect to %s: %s", serial, result.stdout)
    return device


async def disconnect(serial: str) -> AdbDevice:
    """Disconnect a device."""
    # Collect logcat sessions to stop (read under lock)
    async with _lock:
        sessions_to_stop = [
            sid for sid, session in _logcat_sessions.items()
            if session.serial == serial
        ]

    # Stop logcat sessions outside the lock (stop_logcat acquires _lock)
    for sid in sessions_to_stop:
        await stop_logcat(sid)

    if not settings.mock_mode:
        await _adb("disconnect", serial)

    async with _lock:
        device = _devices.get(serial, AdbDevice(serial=serial))
        device.state = AdbDeviceState.DISCONNECTED
        _devices[serial] = device
    logger.info("Disconnected %s", serial)
    return device


async def list_devices() -> List[AdbDevice]:
    """List all known devices with current status."""
    if settings.mock_mode and not _devices:
        return _mock_device_list()

    if not settings.mock_mode:
        result = await _adb("devices", "-l")
        if result.success:
            _parse_devices_output(result.stdout)

    return list(_devices.values())


async def _populate_device_info(device: AdbDevice) -> None:
    """Fetch device properties after connection."""
    props = {
        "manufacturer": "ro.product.manufacturer",
        "model": "ro.product.model",
        "product": "ro.product.name",
        "android_version": "ro.build.version.release",
        "sdk_version": "ro.build.version.sdk",
    }
    for attr, prop in props.items():
        result = await _adb("-s", device.serial, "shell", "getprop", prop)
        if result.success and result.stdout:
            setattr(device, attr, result.stdout.strip())

    # Display resolution (with bounds check to avoid IndexError)
    result = await _adb("-s", device.serial, "shell", "wm", "size")
    if result.success and "Physical size" in result.stdout:
        parts = result.stdout.split(":")
        if len(parts) >= 2:
            device.display_resolution = parts[1].strip()


def _parse_devices_output(output: str) -> None:
    """Parse 'adb devices -l' output."""
    for line in output.splitlines()[1:]:  # skip header
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 2:
            serial = parts[0]
            state_str = parts[1]

            state_map = {
                "device": AdbDeviceState.CONNECTED,
                "offline": AdbDeviceState.OFFLINE,
                "unauthorized": AdbDeviceState.UNAUTHORIZED,
            }
            state = state_map.get(state_str, AdbDeviceState.DISCONNECTED)

            if serial in _devices:
                _devices[serial].state = state
            else:
                device = AdbDevice(serial=serial, state=state)
                # Parse extended info
                for part in parts[2:]:
                    if part.startswith("model:"):
                        device.model = part.split(":")[1]
                    elif part.startswith("product:"):
                        device.product = part.split(":")[1]
                    elif part.startswith("transport_id:"):
                        device.transport_id = part.split(":")[1]
                _devices[serial] = device


# --- Shell commands ---

async def shell(serial: str, command: str, timeout: int = 30) -> AdbShellResult:
    """Execute a shell command on a device."""
    if settings.mock_mode:
        return _mock_shell_result(serial, command)

    result = await _adb("-s", serial, "shell", command, timeout=float(timeout))
    return AdbShellResult(
        serial=serial,
        command=command,
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.returncode,
    )


# --- Key events ---

async def send_key(serial: str, keycode: str) -> AdbShellResult:
    """Send a key event to a device."""
    # Resolve friendly name to keycode
    from ..models.adb import STB_KEYCODES
    resolved = STB_KEYCODES.get(keycode.lower(), keycode)

    return await shell(serial, f"input keyevent {resolved}")


# --- Logcat ---

async def start_logcat(
    serial: str,
    filters: Optional[List[str]] = None,
    scenario_id: Optional[str] = None,
) -> LogcatSession:
    """Start streaming logcat from a device."""
    session_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()

    session = LogcatSession(
        id=session_id,
        serial=serial,
        filters=filters or [],
        active=True,
        started_at=now,
        scenario_id=scenario_id,
    )

    async with _lock:
        _logcat_sessions[session_id] = session
        _logcat_buffers[session_id] = deque(maxlen=MAX_LOGCAT_LINES)

    if settings.mock_mode:
        logger.info("Mock logcat session started: %s", session_id)
        # Add some mock lines
        async with _lock:
            buf = _logcat_buffers[session_id]
            for i in range(5):
                buf.append(LogcatLine(
                    timestamp=now,
                    pid="1234",
                    level="I",
                    tag="MediaPlayer",
                    message=f"Mock logcat line {i}",
                    raw=f"04-02 22:00:00.{i:03d}  1234  1234 I MediaPlayer: Mock logcat line {i}",
                ))
                session.line_count += 1
        return session

    # Build logcat command
    cmd = ["adb", "-s", serial, "logcat", "-v", "threadtime"]
    for f in (filters or []):
        cmd.append(f)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async with _lock:
        _logcat_processes[session_id] = proc
    asyncio.create_task(_stream_logcat(session_id, proc))

    logger.info("Started logcat session %s for %s", session_id, serial)
    return session


async def _stream_logcat(session_id: str, proc: asyncio.subprocess.Process) -> None:
    """Background task reading logcat output."""
    try:
        while True:
            line_bytes = await proc.stdout.readline()
            if not line_bytes:
                break

            raw = line_bytes.decode("utf-8", errors="replace").rstrip()
            if not raw:
                continue

            parsed = _parse_logcat_line(raw)
            buf = _logcat_buffers.get(session_id)
            if buf is not None:
                buf.append(parsed)
                session = _logcat_sessions.get(session_id)
                if session:
                    session.line_count += 1

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error("Logcat stream error for %s: %s", session_id, e)
    finally:
        session = _logcat_sessions.get(session_id)
        if session:
            session.active = False
        _logcat_processes.pop(session_id, None)


def _parse_logcat_line(raw: str) -> LogcatLine:
    """Parse a logcat threadtime format line."""
    # Format: MM-DD HH:MM:SS.mmm  PID  TID LEVEL TAG: message
    match = re.match(
        r"(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+(\d+)\s+(\d+)\s+([VDIWEF])\s+(\S+?)\s*:\s*(.*)",
        raw,
    )
    if match:
        return LogcatLine(
            timestamp=match.group(1),
            pid=match.group(2),
            tid=match.group(3),
            level=match.group(4),
            tag=match.group(5),
            message=match.group(6),
            raw=raw,
        )
    return LogcatLine(raw=raw, message=raw)


async def stop_logcat(session_id: str) -> LogcatSession:
    """Stop a logcat session."""
    async with _lock:
        session = _logcat_sessions.get(session_id)
        if not session:
            raise ValueError(f"Logcat session {session_id} not found")
        proc = _logcat_processes.get(session_id)

    if proc and proc.returncode is None:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=3)
        except asyncio.TimeoutError:
            proc.kill()

    async with _lock:
        session.active = False
    logger.info("Stopped logcat session %s", session_id)
    return session


def get_logcat_lines(
    session_id: str,
    last_n: int = 200,
    level_filter: Optional[str] = None,
    tag_filter: Optional[str] = None,
) -> List[LogcatLine]:
    """Get recent logcat lines from a session."""
    buf = _logcat_buffers.get(session_id)
    if not buf:
        return []

    lines = list(buf)[-last_n:]

    if level_filter:
        levels = set(level_filter.upper())
        lines = [l for l in lines if l.level in levels]

    if tag_filter:
        lines = [l for l in lines if tag_filter.lower() in l.tag.lower()]

    return lines


def list_logcat_sessions() -> List[LogcatSession]:
    """List all logcat sessions."""
    return list(_logcat_sessions.values())


# --- File operations ---

async def pull_file(serial: str, remote_path: str) -> str:
    """Pull a file from device to local storage. Returns local path."""
    store = FILE_STORE if not settings.mock_mode else Path("/tmp/wifry-adb-files")
    store.mkdir(parents=True, exist_ok=True)

    filename = Path(remote_path).name
    local_path = store / f"{serial.replace(':', '_')}_{filename}"

    if settings.mock_mode:
        local_path.write_text(f"Mock file content from {remote_path}")
        return str(local_path)

    result = await _adb("-s", serial, "pull", remote_path, str(local_path))
    if not result.success:
        raise RuntimeError(f"adb pull failed: {result.stderr}")
    return str(local_path)


async def push_file(serial: str, local_path: str, remote_path: str) -> str:
    """Push a file to device."""
    if settings.mock_mode:
        return remote_path

    result = await _adb("-s", serial, "push", local_path, remote_path)
    if not result.success:
        raise RuntimeError(f"adb push failed: {result.stderr}")
    return remote_path


async def install_apk(serial: str, apk_path: str) -> str:
    """Install an APK on the device."""
    if settings.mock_mode:
        return "Success (mock)"

    result = await _adb("-s", serial, "install", "-r", apk_path, timeout=120)
    if not result.success:
        raise RuntimeError(f"Install failed: {result.stderr or result.stdout}")
    return result.stdout


async def screencap(serial: str) -> str:
    """Capture screenshot. Returns local path to PNG."""
    store = FILE_STORE if not settings.mock_mode else Path("/tmp/wifry-adb-files")
    store.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    local_path = store / f"screen_{serial.replace(':', '_')}_{ts}.png"

    if settings.mock_mode:
        local_path.write_bytes(b"MOCK PNG")
        return str(local_path)

    remote_path = "/sdcard/wifry_screen.png"
    await shell(serial, f"screencap -p {remote_path}")
    await _adb("-s", serial, "pull", remote_path, str(local_path))
    await shell(serial, f"rm {remote_path}")
    return str(local_path)


async def bugreport(serial: str) -> str:
    """Capture bugreport. Returns local path."""
    store = FILE_STORE if not settings.mock_mode else Path("/tmp/wifry-adb-files")
    store.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    local_path = store / f"bugreport_{serial.replace(':', '_')}_{ts}.zip"

    if settings.mock_mode:
        local_path.write_bytes(b"MOCK BUGREPORT")
        return str(local_path)

    result = await _adb("-s", serial, "bugreport", str(local_path), timeout=300)
    if not result.success:
        raise RuntimeError(f"Bugreport failed: {result.stderr}")
    return str(local_path)


# --- Mock helpers ---

def _mock_device(serial: str) -> AdbDevice:
    return AdbDevice(
        serial=serial,
        state=AdbDeviceState.CONNECTED,
        model="TiVo Stream 4K",
        manufacturer="TiVo",
        product="kingfisher",
        android_version="12",
        sdk_version="31",
        display_resolution="1920x1080",
    )


def _mock_device_list() -> List[AdbDevice]:
    return [
        _mock_device("192.168.4.10:5555"),
        AdbDevice(
            serial="192.168.4.11:5555",
            state=AdbDeviceState.CONNECTED,
            model="Chromecast with Google TV",
            manufacturer="Google",
            android_version="12",
        ),
    ]


def _mock_shell_result(serial: str, command: str) -> AdbShellResult:
    if "dumpsys media" in command:
        return AdbShellResult(serial=serial, command=command, stdout="Mock media dumpsys output...")
    if "getprop" in command:
        return AdbShellResult(serial=serial, command=command, stdout="mock_value")
    return AdbShellResult(serial=serial, command=command, stdout=f"$ {command}\n(mock output)")
