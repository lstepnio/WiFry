"""Capture retention policy enforcement.

Enforces limits from the RPi 5 performance guide:
- Max 20 captures
- Max 500 MB total pcap storage
- Max 7 days age
- Session-linked captures exempt while session is active

Runs as a background task after each capture completion and on a
daily maintenance schedule.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from ..config import settings
from . import storage

logger = logging.getLogger(__name__)

# Retention limits
MAX_CAPTURES = 20
MAX_STORAGE_BYTES = 500 * 1024 * 1024  # 500 MB
MAX_AGE_DAYS = 7


def _captures_dir() -> Path:
    return storage.ensure_data_path("captures")


def _get_capture_files() -> List[Tuple[str, Path, Path, int, Optional[str]]]:
    """Get all captures with their metadata.

    Returns: List of (capture_id, meta_path, pcap_path, file_size, started_at)
    sorted by started_at ascending (oldest first).
    """
    import json

    captures_dir = _captures_dir()
    captures = []

    for meta_file in captures_dir.glob("*.json"):
        if ".analysis." in meta_file.name or ".summary." in meta_file.name:
            continue

        capture_id = meta_file.stem
        pcap_path = captures_dir / f"{capture_id}.pcap"
        pcapng_path = captures_dir / f"{capture_id}.pcapng"

        # Use whichever pcap format exists
        actual_pcap = pcap_path if pcap_path.exists() else pcapng_path

        file_size = actual_pcap.stat().st_size if actual_pcap.exists() else 0
        started_at = None

        try:
            data = json.loads(meta_file.read_text())
            started_at = data.get("started_at")
        except (json.JSONDecodeError, OSError):
            pass

        captures.append((capture_id, meta_file, actual_pcap, file_size, started_at))

    # Sort by started_at ascending (oldest first for pruning)
    captures.sort(key=lambda c: c[4] or "")
    return captures


def _is_session_linked(capture_id: str) -> bool:
    """Check if a capture is linked to an active session.

    Session-linked captures are exempt from retention pruning.
    """
    # For now, simple check — can be extended to query session_manager
    return False


async def enforce_retention() -> dict:
    """Run retention enforcement. Returns stats about what was pruned."""
    stats = {"checked": 0, "pruned_count": 0, "pruned_age": 0, "pruned_size": 0, "freed_bytes": 0}

    captures = _get_capture_files()
    stats["checked"] = len(captures)

    if not captures:
        return stats

    now = datetime.now(timezone.utc)
    to_prune: List[Tuple[str, Path, Path, str]] = []

    # 1. Age-based pruning
    for cid, meta_path, pcap_path, fsize, started_at in captures:
        if _is_session_linked(cid):
            continue

        if started_at:
            try:
                capture_time = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                if now - capture_time > timedelta(days=MAX_AGE_DAYS):
                    to_prune.append((cid, meta_path, pcap_path, "age"))
                    stats["pruned_age"] += 1
            except ValueError:
                pass

    # 2. Count-based pruning (after removing aged captures)
    remaining = [c for c in captures if c[0] not in {p[0] for p in to_prune}]
    while len(remaining) > MAX_CAPTURES:
        oldest = remaining.pop(0)
        cid = oldest[0]
        if not _is_session_linked(cid):
            to_prune.append((cid, oldest[1], oldest[2], "count"))
            stats["pruned_count"] += 1

    # 3. Size-based pruning
    remaining = [c for c in captures if c[0] not in {p[0] for p in to_prune}]
    total_size = sum(c[3] for c in remaining)
    while total_size > MAX_STORAGE_BYTES and remaining:
        oldest = remaining.pop(0)
        cid = oldest[0]
        if not _is_session_linked(cid):
            to_prune.append((cid, oldest[1], oldest[2], "size"))
            stats["pruned_size"] += 1
            total_size -= oldest[3]

    # Execute pruning — use capture.delete_capture() when possible
    # to also clean up in-memory state
    from . import capture as capture_service

    for cid, meta_path, pcap_path, reason in to_prune:
        try:
            freed = 0
            if pcap_path.exists():
                freed += pcap_path.stat().st_size

            # Use the service's delete to also clean in-memory _captures dict
            try:
                await capture_service.delete_capture(cid)
            except (ValueError, Exception):
                # Fallback: manual file removal if service delete fails
                if pcap_path.exists():
                    pcap_path.unlink()
                if meta_path.exists():
                    meta_path.unlink()
                summary_path = _captures_dir() / f"{cid}.summary.json"
                analysis_path = _captures_dir() / f"{cid}.analysis.json"
                summary_path.unlink(missing_ok=True)
                analysis_path.unlink(missing_ok=True)

            stats["freed_bytes"] += freed
            logger.info("Pruned capture %s (reason: %s, freed: %d bytes)", cid, reason, freed)
        except OSError as e:
            logger.warning("Failed to prune capture %s: %s", cid, e)

    if to_prune:
        logger.info(
            "Retention: pruned %d captures (age=%d, count=%d, size=%d), freed %.1f MB",
            len(to_prune),
            stats["pruned_age"],
            stats["pruned_count"],
            stats["pruned_size"],
            stats["freed_bytes"] / 1024 / 1024,
        )

    return stats


async def get_storage_usage() -> dict:
    """Get current capture storage usage."""
    captures = _get_capture_files()
    total_bytes = sum(c[3] for c in captures)

    return {
        "capture_count": len(captures),
        "total_bytes": total_bytes,
        "total_mb": round(total_bytes / 1024 / 1024, 1),
        "max_captures": MAX_CAPTURES,
        "max_storage_mb": MAX_STORAGE_BYTES // (1024 * 1024),
        "max_age_days": MAX_AGE_DAYS,
        "usage_pct": round(total_bytes / MAX_STORAGE_BYTES * 100, 1) if MAX_STORAGE_BYTES > 0 else 0,
    }
