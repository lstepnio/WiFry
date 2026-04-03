"""Notes and tags annotation system.

Allows attaching notes and tags to any data point (captures, streams,
scenarios, devices) so observations don't get lost in the data.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..config import settings

logger = logging.getLogger(__name__)

ANNOTATIONS_DIR = Path("/var/lib/wifry/annotations") if not settings.mock_mode else Path("/tmp/wifry-annotations")

# In-memory store
_annotations: Dict[str, dict] = {}


def _ensure_dir() -> Path:
    ANNOTATIONS_DIR.mkdir(parents=True, exist_ok=True)
    return ANNOTATIONS_DIR


def add_annotation(
    target_type: str,  # "capture", "stream", "device", "scenario", "general"
    target_id: str,
    note: str,
    tags: Optional[List[str]] = None,
) -> dict:
    """Add an annotation to a data point."""
    ann_id = uuid.uuid4().hex[:10]
    now = datetime.now(timezone.utc).isoformat()

    annotation = {
        "id": ann_id,
        "target_type": target_type,
        "target_id": target_id,
        "note": note,
        "tags": tags or [],
        "created_at": now,
    }

    _annotations[ann_id] = annotation
    _save(ann_id, annotation)
    return annotation


def get_annotations(
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    tag: Optional[str] = None,
) -> List[dict]:
    """Get annotations, optionally filtered."""
    _load_all()
    results = list(_annotations.values())

    if target_type:
        results = [a for a in results if a["target_type"] == target_type]
    if target_id:
        results = [a for a in results if a["target_id"] == target_id]
    if tag:
        results = [a for a in results if tag in a.get("tags", [])]

    return sorted(results, key=lambda a: a["created_at"], reverse=True)


def delete_annotation(ann_id: str) -> None:
    _annotations.pop(ann_id, None)
    path = _ensure_dir() / f"{ann_id}.json"
    path.unlink(missing_ok=True)


def _save(ann_id: str, data: dict) -> None:
    path = _ensure_dir() / f"{ann_id}.json"
    path.write_text(json.dumps(data, indent=2))


def _load_all() -> None:
    d = _ensure_dir()
    for f in d.glob("*.json"):
        aid = f.stem
        if aid not in _annotations:
            try:
                _annotations[aid] = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                pass
