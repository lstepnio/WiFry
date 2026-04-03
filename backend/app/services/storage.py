"""External storage management.

Detects and mounts USB storage devices for storing captures, logs,
HDMI recordings, and segment data instead of the RPi's SD card.

When external storage is enabled, all data paths (captures, logs,
segments, HDMI frames, recordings) are redirected to the USB mount.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from ..config import settings
from ..utils.shell import run

logger = logging.getLogger(__name__)

MOUNT_BASE = Path("/media/wifry")
CONFIG_PATH = Path("/var/lib/wifry/storage.json") if not settings.mock_mode else Path("/tmp/wifry-storage.json")

_active_mount: Optional[str] = None


async def detect_devices() -> List[dict]:
    """Detect connected USB storage devices."""
    if settings.mock_mode:
        return [
            {
                "device": "/dev/sda1",
                "label": "WIFRY_USB",
                "filesystem": "ext4",
                "size_bytes": 128_000_000_000,
                "size_human": "128 GB",
                "mounted": False,
                "mount_point": "",
            },
        ]

    result = await run("lsblk", "-J", "-o", "NAME,SIZE,FSTYPE,LABEL,MOUNTPOINT,TYPE", check=False)
    if not result.success:
        return []

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    devices = []
    for bd in data.get("blockdevices", []):
        # Look for partitions on USB devices
        children = bd.get("children", [])
        if not children and bd.get("type") == "part":
            children = [bd]

        for part in children:
            if part.get("type") != "part":
                continue
            if not part.get("fstype"):
                continue

            device = f"/dev/{part['name']}"
            devices.append({
                "device": device,
                "label": part.get("label", ""),
                "filesystem": part.get("fstype", ""),
                "size_human": part.get("size", ""),
                "mounted": bool(part.get("mountpoint")),
                "mount_point": part.get("mountpoint", ""),
            })

    return devices


async def mount_device(device: str) -> dict:
    """Mount a USB storage device for WiFry data."""
    global _active_mount

    mount_point = MOUNT_BASE / "data"

    if settings.mock_mode:
        _active_mount = str(mount_point)
        _save_config(device, str(mount_point))
        logger.info("Mock: mounted %s at %s", device, mount_point)
        return {"status": "ok", "device": device, "mount_point": str(mount_point)}

    mount_point.mkdir(parents=True, exist_ok=True)

    result = await run("mount", device, str(mount_point), sudo=True, check=False)
    if not result.success:
        return {"status": "error", "message": result.stderr}

    # Create subdirectories
    for subdir in ["captures", "logs", "segments", "hdmi", "reports", "adb-files", "annotations"]:
        (mount_point / subdir).mkdir(exist_ok=True)

    # Set ownership
    await run("chown", "-R", "wifry:wifry", str(mount_point), sudo=True, check=False)

    _active_mount = str(mount_point)
    _save_config(device, str(mount_point))

    logger.info("Mounted %s at %s", device, mount_point)
    return {"status": "ok", "device": device, "mount_point": str(mount_point)}


async def unmount() -> dict:
    """Unmount external storage and revert to SD card paths."""
    global _active_mount

    if settings.mock_mode:
        _active_mount = None
        _save_config("", "")
        return {"status": "ok"}

    if _active_mount:
        await run("umount", _active_mount, sudo=True, check=False)
        _active_mount = None

    _save_config("", "")
    return {"status": "ok"}


def get_status() -> dict:
    """Get current storage status."""
    return {
        "external_active": _active_mount is not None,
        "mount_point": _active_mount,
        "paths": get_data_paths(),
    }


def get_data_paths() -> dict:
    """Get the current data paths (external or default)."""
    if _active_mount:
        base = Path(_active_mount)
        return {
            "captures": str(base / "captures"),
            "logs": str(base / "logs"),
            "segments": str(base / "segments"),
            "hdmi": str(base / "hdmi"),
            "reports": str(base / "reports"),
            "adb_files": str(base / "adb-files"),
            "annotations": str(base / "annotations"),
        }
    else:
        # Default SD card paths
        base = "/var/lib/wifry" if not settings.mock_mode else "/tmp/wifry"
        return {
            "captures": f"{base}/captures",
            "logs": f"{base}/logs",
            "segments": f"{base}/segments",
            "hdmi": f"{base}/hdmi-captures",
            "reports": f"{base}/reports",
            "adb_files": f"{base}/adb-files",
            "annotations": f"{base}/annotations",
        }


async def get_usage() -> dict:
    """Get storage usage stats."""
    paths = get_data_paths()
    usage = {}

    for name, path in paths.items():
        p = Path(path)
        if p.exists():
            total = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            count = sum(1 for f in p.rglob("*") if f.is_file())
            usage[name] = {
                "path": path,
                "size_bytes": total,
                "size_mb": round(total / (1024 * 1024), 2),
                "file_count": count,
            }
        else:
            usage[name] = {"path": path, "size_bytes": 0, "size_mb": 0, "file_count": 0}

    # Total
    total_bytes = sum(u["size_bytes"] for u in usage.values())
    usage["_total"] = {
        "size_bytes": total_bytes,
        "size_mb": round(total_bytes / (1024 * 1024), 2),
        "file_count": sum(u["file_count"] for u in usage.values()),
    }

    return usage


def _save_config(device: str, mount_point: str) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({"device": device, "mount_point": mount_point}))


def _load_config() -> None:
    global _active_mount
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text())
            mp = data.get("mount_point", "")
            if mp and Path(mp).exists():
                _active_mount = mp
        except (json.JSONDecodeError, OSError):
            pass


# Load on import
_load_config()
