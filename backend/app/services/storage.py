"""Shared data-path resolution and external storage management.

All services that persist runtime artifacts should resolve their paths
through this module instead of hardcoding `/var/lib/wifry/...` or ad hoc
mock-mode directories. That keeps default, mock, and external-storage
layouts aligned across captures, sessions, reports, ADB artifacts, and
scenario metadata.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from ..config import settings
from ..utils.shell import run

logger = logging.getLogger(__name__)

MOUNT_BASE = Path("/media/wifry")
CONFIG_PATH = settings.data_dir / "storage.json" if not settings.mock_mode else Path("/tmp/wifry-storage.json")

_active_mount: Optional[str] = None

_PUBLIC_DATA_SUBDIRS: Dict[str, str] = {
    "captures": "captures",
    "logs": "logs",
    "segments": "segments",
    "hdmi": "hdmi",
    "reports": "reports",
    "adb_files": "adb-files",
    "annotations": "annotations",
    "sessions": "sessions",
    "scenarios": "scenarios",
}

_PRIVATE_DATA_SUBDIRS: Dict[str, str] = {
    "runtime_state": "runtime-state",
}

_ALL_DATA_SUBDIRS: Dict[str, str] = {
    **_PUBLIC_DATA_SUBDIRS,
    **_PRIVATE_DATA_SUBDIRS,
}

_MOCK_PATHS: Dict[str, Path] = {
    "captures": Path("/tmp/wifry-captures"),
    "logs": Path("/tmp/wifry-logs"),
    "segments": Path("/tmp/wifry-segments"),
    "hdmi": Path("/tmp/wifry-hdmi"),
    "reports": Path("/tmp/wifry-reports"),
    "adb_files": Path("/tmp/wifry-adb-files"),
    "annotations": Path("/tmp/wifry-annotations"),
    "sessions": Path("/tmp/wifry-sessions"),
    "scenarios": Path("/tmp/wifry-scenarios"),
    "runtime_state": Path("/tmp/wifry-runtime-state"),
}


def _default_paths() -> Dict[str, Path]:
    return {
        "captures": settings.captures_dir,
        "logs": settings.data_dir / "logs",
        "segments": settings.data_dir / "segments",
        "hdmi": settings.data_dir / "hdmi-captures",
        "reports": settings.data_dir / "reports",
        "adb_files": settings.data_dir / "adb-files",
        "annotations": settings.data_dir / "annotations",
        "sessions": settings.data_dir / "sessions",
        "scenarios": settings.data_dir / "scenarios",
        "runtime_state": settings.data_dir / "runtime-state",
    }


def get_data_path(name: str) -> Path:
    """Resolve a named runtime data path."""
    if name not in _ALL_DATA_SUBDIRS:
        raise ValueError(f"Unknown data path '{name}'")

    if _active_mount:
        return Path(_active_mount) / _ALL_DATA_SUBDIRS[name]

    if settings.mock_mode:
        return _MOCK_PATHS[name]

    return _default_paths()[name]


def ensure_data_path(name: str) -> Path:
    """Resolve and create a named runtime data path."""
    path = get_data_path(name)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_data_paths(include_private: bool = False) -> dict:
    """Get the current public data paths.

    Private runtime-state paths stay hidden by default so they are not exposed
    through sharing or bundle-style endpoints.
    """
    names = _ALL_DATA_SUBDIRS if include_private else _PUBLIC_DATA_SUBDIRS
    return {name: str(get_data_path(name)) for name in names}


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
    for block_device in data.get("blockdevices", []):
        children = block_device.get("children", [])
        if not children and block_device.get("type") == "part":
            children = [block_device]

        for part in children:
            if part.get("type") != "part" or not part.get("fstype"):
                continue

            devices.append({
                "device": f"/dev/{part['name']}",
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

    for subdir in set(_ALL_DATA_SUBDIRS.values()):
        (mount_point / subdir).mkdir(exist_ok=True)

    await run("chown", "-R", "wifry:wifry", str(mount_point), sudo=True, check=False)

    _active_mount = str(mount_point)
    _save_config(device, str(mount_point))

    logger.info("Mounted %s at %s", device, mount_point)
    return {"status": "ok", "device": device, "mount_point": str(mount_point)}


async def unmount() -> dict:
    """Unmount external storage and revert to default paths."""
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


async def get_usage() -> dict:
    """Get storage usage stats."""
    usage = {}

    for name, path_str in get_data_paths().items():
        path = Path(path_str)
        if path.exists():
            total = sum(file.stat().st_size for file in path.rglob("*") if file.is_file())
            count = sum(1 for file in path.rglob("*") if file.is_file())
            usage[name] = {
                "path": path_str,
                "size_bytes": total,
                "size_mb": round(total / (1024 * 1024), 2),
                "file_count": count,
            }
        else:
            usage[name] = {
                "path": path_str,
                "size_bytes": 0,
                "size_mb": 0,
                "file_count": 0,
            }

    total_bytes = sum(item["size_bytes"] for item in usage.values())
    usage["_total"] = {
        "size_bytes": total_bytes,
        "size_mb": round(total_bytes / (1024 * 1024), 2),
        "file_count": sum(item["file_count"] for item in usage.values()),
    }

    return usage


def _save_config(device: str, mount_point: str) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({"device": device, "mount_point": mount_point}))


def _load_config() -> None:
    global _active_mount
    if not CONFIG_PATH.exists():
        return

    try:
        data = json.loads(CONFIG_PATH.read_text())
        mount_point = data.get("mount_point", "")
        if mount_point and Path(mount_point).exists():
            _active_mount = mount_point
    except (json.JSONDecodeError, OSError):
        pass


_load_config()
