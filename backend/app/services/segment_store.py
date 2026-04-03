"""Optional segment storage for offline analysis."""

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from ..config import settings

logger = logging.getLogger(__name__)

SEGMENTS_DIR = Path("/var/lib/wifry/segments")


def _ensure_dir() -> Path:
    d = SEGMENTS_DIR if not settings.mock_mode else Path("/tmp/wifry-segments")
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_segment(
    session_id: str,
    sequence: int,
    data: bytes,
    extension: str = ".ts",
) -> str:
    """Save a segment to disk. Returns the saved file path."""
    d = _ensure_dir() / session_id
    d.mkdir(parents=True, exist_ok=True)

    filename = f"seg_{sequence:06d}{extension}"
    path = d / filename
    path.write_bytes(data)

    logger.debug("Saved segment: %s (%d bytes)", path, len(data))
    return str(path)


def get_storage_usage_mb() -> float:
    """Get total storage used by saved segments in MB."""
    d = _ensure_dir()
    total = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
    return round(total / (1024 * 1024), 2)


def cleanup_old_segments(max_mb: int = 500) -> int:
    """Remove oldest segments to stay under storage limit. Returns files removed."""
    d = _ensure_dir()
    files = sorted(d.rglob("*"), key=lambda f: f.stat().st_mtime if f.is_file() else 0)

    removed = 0
    while get_storage_usage_mb() > max_mb and files:
        f = files.pop(0)
        if f.is_file():
            f.unlink()
            removed += 1

    if removed:
        # Clean up empty session directories
        for subdir in d.iterdir():
            if subdir.is_dir() and not any(subdir.iterdir()):
                subdir.rmdir()

    return removed


def get_session_segments(session_id: str) -> List[dict]:
    """List saved segments for a session."""
    d = _ensure_dir() / session_id
    if not d.exists():
        return []

    segments = []
    for f in sorted(d.iterdir()):
        if f.is_file():
            segments.append({
                "filename": f.name,
                "size_bytes": f.stat().st_size,
                "path": str(f),
            })
    return segments
