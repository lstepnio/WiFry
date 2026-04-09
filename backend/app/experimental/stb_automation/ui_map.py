"""UI Map — learned menu navigation patterns with disk persistence.

Tracks how D-pad actions move focus between menu items on each screen.
After enough observations, predicts the next focused element without
an AI vision call.

All state access goes through module functions (get/put pattern) so the
backing store can be swapped to Redis/SQLite by changing only this file.
Keys are activity-based (device-agnostic) — shared maps across
same-model STBs work naturally.
"""

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ...services import storage
from .models import UIMapEntry

logger = logging.getLogger("wifry.stb_automation.ui_map")

_MAP_FILE = "ui_map.json"
_FORMAT_VERSION = 1

# ── In-memory state ────────────────────────────────────────────────

# entries[screen_key][(action, from_focused)] = UIMapEntry
_entries: Dict[str, Dict[Tuple[str, str], UIMapEntry]] = defaultdict(dict)

# Last known focused label per screen_key (for prediction context)
_last_focused: Dict[str, str] = {}

# Last navigate action (set by router before /state call)
_last_action: str = ""

# Stats
_total_observations: int = 0
_total_predictions: int = 0
_total_prediction_hits: int = 0
_total_prediction_misses: int = 0

_dirty: bool = False


# ── Confidence model ───────────────────────────────────────────────


def _compute_confidence(observation_count: int) -> float:
    """Derive confidence from observation count.

    1 observation  → 0.3 (seen once, might be ephemeral)
    2 observations → 0.6 (seen twice, likely persistent)
    3+ observations → 0.85 + 0.05 * min(count - 3, 3) → max 1.0
    """
    if observation_count <= 0:
        return 0.0
    if observation_count == 1:
        return 0.3
    if observation_count == 2:
        return 0.6
    return min(1.0, 0.85 + 0.05 * min(observation_count - 3, 3))


# ── Persistence ────────────────────────────────────────────────────


def _map_path() -> Path:
    return storage.ensure_data_path("runtime_state") / _MAP_FILE


def load() -> int:
    """Load map from disk. Returns number of entries loaded."""
    global _dirty, _total_observations, _total_predictions, _total_prediction_hits, _total_prediction_misses
    path = _map_path()
    if not path.exists():
        return 0

    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or data.get("version") != _FORMAT_VERSION:
            logger.warning("UI map file has unknown format, starting fresh")
            return 0

        count = 0
        for screen_key, transitions in data.get("entries", {}).items():
            for t in transitions:
                try:
                    entry = UIMapEntry.model_validate(t)
                    key = (entry.action, entry.from_focused)
                    _entries[screen_key][key] = entry
                    count += 1
                except Exception:
                    pass

        # Restore stats
        s = data.get("stats", {})
        _total_observations = s.get("total_observations", 0)
        _total_predictions = s.get("total_predictions", 0)
        _total_prediction_hits = s.get("total_prediction_hits", 0)
        _total_prediction_misses = s.get("total_prediction_misses", 0)

        # Restore last_focused
        _last_focused.update(data.get("last_focused", {}))

        _dirty = False
        logger.info("UI map loaded: %d entries across %d screens from %s",
                     count, len(_entries), path)
        return count

    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load UI map: %s", e)
        return 0


def save() -> int:
    """Save map to disk if dirty. Returns total entry count."""
    global _dirty
    if not _dirty:
        return sum(len(v) for v in _entries.values())

    path = _map_path()
    tmp_path = path.with_suffix(".json.tmp")

    serialized_entries = {}
    for screen_key, transitions in _entries.items():
        serialized_entries[screen_key] = [
            entry.model_dump() for entry in transitions.values()
        ]

    data = {
        "version": _FORMAT_VERSION,
        "entries": serialized_entries,
        "stats": {
            "total_observations": _total_observations,
            "total_predictions": _total_predictions,
            "total_prediction_hits": _total_prediction_hits,
            "total_prediction_misses": _total_prediction_misses,
        },
        "last_focused": dict(_last_focused),
    }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(json.dumps(data, separators=(",", ":")))
        os.replace(str(tmp_path), str(path))
        _dirty = False
        total = sum(len(v) for v in _entries.values())
        logger.info("UI map saved: %d entries to %s", total, path)
        return total
    except OSError as e:
        logger.warning("Failed to save UI map: %s", e)
        return 0


# ── Navigation context ─────────────────────────────────────────────


def set_last_action(action: str) -> None:
    """Record the last navigate action (called by router before /state)."""
    global _last_action
    _last_action = action


def get_last_action() -> str:
    """Get the last navigate action."""
    return _last_action


def set_last_focused(screen_key: str, focused_label: str) -> None:
    """Update the last known focused label for a screen."""
    global _dirty
    if focused_label:
        _last_focused[screen_key] = focused_label
        _dirty = True


def get_last_focused(screen_key: str) -> str:
    """Get the last known focused label for a screen."""
    return _last_focused.get(screen_key, "")


# ── Predict ────────────────────────────────────────────────────────


def predict(
    screen_key: str,
    action: str,
    from_focused: str,
    min_confidence: float = 0.7,
    min_observations: int = 2,
) -> Optional[UIMapEntry]:
    """Predict the result of an action from current state.

    Returns None if no prediction available or confidence too low.
    """
    global _total_predictions
    if not screen_key or not action or not from_focused:
        return None

    transitions = _entries.get(screen_key)
    if not transitions:
        return None

    entry = transitions.get((action, from_focused))
    if entry is None:
        return None

    if entry.confidence < min_confidence or entry.observation_count < min_observations:
        return None

    _total_predictions += 1
    return entry


# ── Observe ────────────────────────────────────────────────────────


def observe(
    screen_key: str,
    action: str,
    from_focused: str,
    to_focused: str,
    to_screen_type: str = "unknown",
    to_screen_title: str = "",
    to_focused_position: str = "",
    to_focused_confidence: str = "low",
    to_navigation_path: Optional[List[str]] = None,
) -> UIMapEntry:
    """Record an observed focus transition. Creates or updates entry."""
    global _total_observations, _dirty

    now = datetime.now(timezone.utc).isoformat()
    key = (action, from_focused)
    transitions = _entries[screen_key]

    existing = transitions.get(key)
    if existing and existing.to_focused == to_focused:
        # Same result — increment count, boost confidence
        existing.observation_count += 1
        existing.confidence = _compute_confidence(existing.observation_count)
        existing.last_observed = now
        # Update fields that may have improved
        if to_screen_type != "unknown":
            existing.to_screen_type = to_screen_type
        if to_screen_title:
            existing.to_screen_title = to_screen_title
        if to_focused_position:
            existing.to_focused_position = to_focused_position
        if to_focused_confidence:
            existing.to_focused_confidence = to_focused_confidence
        if to_navigation_path:
            existing.to_navigation_path = to_navigation_path
        _total_observations += 1
        _dirty = True
        return existing

    # Different result or new entry — create/replace
    entry = UIMapEntry(
        screen_key=screen_key,
        action=action,
        from_focused=from_focused,
        to_focused=to_focused,
        to_screen_type=to_screen_type,
        to_screen_title=to_screen_title,
        to_focused_position=to_focused_position,
        to_focused_confidence=to_focused_confidence,
        to_navigation_path=to_navigation_path or [],
        observation_count=1,
        confidence=_compute_confidence(1),
        last_observed=now,
    )

    if existing:
        # Result changed — reset confidence (menu may have changed)
        logger.info("UI map entry changed: %s/%s/%s: %s → %s (was %s)",
                     screen_key, action, from_focused, from_focused, to_focused,
                     existing.to_focused)

    transitions[key] = entry
    _total_observations += 1
    _dirty = True
    return entry


# ── Validate ───────────────────────────────────────────────────────


def validate(
    screen_key: str,
    action: str,
    from_focused: str,
    actual_focused: str,
) -> bool:
    """Validate a prediction against actual AI result.

    Returns True if prediction was correct. Decays confidence on miss.
    """
    global _total_prediction_hits, _total_prediction_misses, _dirty

    transitions = _entries.get(screen_key)
    if not transitions:
        return False

    entry = transitions.get((action, from_focused))
    if entry is None:
        return False

    if entry.to_focused == actual_focused:
        _total_prediction_hits += 1
        # Boost via observation
        entry.observation_count += 1
        entry.confidence = _compute_confidence(entry.observation_count)
        entry.last_observed = datetime.now(timezone.utc).isoformat()
        _dirty = True
        return True

    # Wrong prediction — decay confidence
    _total_prediction_misses += 1
    entry.confidence = max(0.0, entry.confidence - 0.3)
    logger.warning("UI map prediction wrong: %s/%s/%s predicted '%s' but got '%s' (conf→%.2f)",
                    screen_key, action, from_focused, entry.to_focused, actual_focused,
                    entry.confidence)
    _dirty = True
    return False


# ── Query ──────────────────────────────────────────────────────────


def get_screen_entries(screen_key: str) -> List[UIMapEntry]:
    """Get all entries for a screen."""
    transitions = _entries.get(screen_key)
    if not transitions:
        return []
    return list(transitions.values())


def get_all_screens() -> List[dict]:
    """Summary of all learned screens."""
    screens = []
    for screen_key, transitions in _entries.items():
        entries_list = list(transitions.values())
        avg_conf = sum(e.confidence for e in entries_list) / len(entries_list) if entries_list else 0
        screens.append({
            "screen_key": screen_key,
            "entry_count": len(entries_list),
            "avg_confidence": round(avg_conf, 2),
            "max_observations": max((e.observation_count for e in entries_list), default=0),
        })
    return screens


def stats() -> dict:
    """Return map statistics."""
    total_entries = sum(len(v) for v in _entries.values())
    pred_total = _total_predictions
    return {
        "total_screens": len(_entries),
        "total_entries": total_entries,
        "total_observations": _total_observations,
        "total_predictions": _total_predictions,
        "total_prediction_hits": _total_prediction_hits,
        "total_prediction_misses": _total_prediction_misses,
        "prediction_accuracy_pct": round(
            _total_prediction_hits / pred_total * 100, 1
        ) if pred_total > 0 else 0.0,
    }


def clear() -> int:
    """Clear all entries. Returns count cleared."""
    global _total_observations, _total_predictions, _total_prediction_hits
    global _total_prediction_misses, _dirty
    count = sum(len(v) for v in _entries.values())
    _entries.clear()
    _last_focused.clear()
    _total_observations = 0
    _total_predictions = 0
    _total_prediction_hits = 0
    _total_prediction_misses = 0
    _dirty = True
    return count
