"""Unified Vision Map — learned STB navigation patterns with disk persistence.

Consolidates the old nav_model (screen-level graph) and ui_map
(element-level transitions) into a single two-layer map:

  Layer 1: VisionScreen — unique screens (package/activity)
  Layer 2: ElementTransition — focus transitions within/between screens

All writers (crawl, manual navigation, AI vision, cache hits) feed the
same map via observe_transition().  Pathfinding operates on element
identity ("go to Settings") not key-press counting.

Backing store can be swapped to Redis/SQLite by changing only this file.
"""

import hashlib
import json
import logging
import os
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from ...config import settings
from ...services import storage
from .models import ElementTransition, VisionAnalysis, VisionScreen

logger = logging.getLogger("wifry.stb_automation.vision_map")

_MAP_FILE = "vision_map.json"
_FORMAT_VERSION = 2

# ── In-memory state ────────────────────────────────────────────────

# Screens: screen_key -> VisionScreen
_screens: Dict[str, VisionScreen] = {}

# Transitions: screen_key -> { (action, from_element) -> ElementTransition }
_transitions: Dict[str, Dict[Tuple[str, str], ElementTransition]] = defaultdict(dict)

# Last known focused element per screen_key
_last_focused: Dict[str, str] = {}

# Last navigate action
_last_action: str = ""

# Stats
_total_observations: int = 0
_total_predictions: int = 0
_total_prediction_hits: int = 0
_total_prediction_misses: int = 0

_dirty: bool = False


# ── Confidence model ───────────────────────────────────────────────


def _compute_confidence(observation_count: int) -> float:
    """1→0.3, 2→0.6, 3+→0.85-1.0."""
    if observation_count <= 0:
        return 0.0
    if observation_count == 1:
        return 0.3
    if observation_count == 2:
        return 0.6
    return min(1.0, 0.85 + 0.05 * min(observation_count - 3, 3))


def _screen_fingerprint(package: str, activity: str) -> str:
    """Compute legacy 12-char hex fingerprint for backward compat."""
    composite = f"{package}/{activity}:"
    return hashlib.sha256(composite.encode()).hexdigest()[:12]


# ── Persistence ────────────────────────────────────────────────────


def _map_path() -> Path:
    return storage.ensure_data_path("runtime_state") / _MAP_FILE


def load() -> int:
    """Load map from disk. Returns number of transitions loaded.

    Reads both v1 (old ui_map.json) and v2 (vision_map.json) formats.
    """
    global _dirty, _total_observations, _total_predictions, _total_prediction_hits, _total_prediction_misses

    # Try new format first
    path = _map_path()
    if path.exists():
        count = _load_v2(path)
        if count >= 0:
            return count

    # Fall back to old ui_map.json
    old_path = storage.ensure_data_path("runtime_state") / "ui_map.json"
    if old_path.exists():
        count = _load_v1(old_path)
        if count > 0:
            _dirty = True  # Re-save in v2 format
            logger.info("Migrated %d entries from ui_map.json to vision_map.json", count)
        return count

    return 0


def _load_v2(path: Path) -> int:
    """Load v2 format. Returns entry count, or -1 if format mismatch."""
    global _dirty, _total_observations, _total_predictions, _total_prediction_hits, _total_prediction_misses
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or data.get("version") != _FORMAT_VERSION:
            return -1

        count = 0
        # Load screens
        for sk, screen_data in data.get("screens", {}).items():
            try:
                _screens[sk] = VisionScreen.model_validate(screen_data)
            except Exception:
                pass

        # Load transitions
        for t_data in data.get("transitions", []):
            try:
                t = ElementTransition.model_validate(t_data)
                _transitions[t.screen_key][(t.action, t.from_element)] = t
                count += 1
            except Exception:
                pass

        # Restore metadata
        s = data.get("stats", {})
        _total_observations = s.get("total_observations", 0)
        _total_predictions = s.get("total_predictions", 0)
        _total_prediction_hits = s.get("total_prediction_hits", 0)
        _total_prediction_misses = s.get("total_prediction_misses", 0)
        _last_focused.update(data.get("last_focused", {}))

        _dirty = False
        logger.info("Vision map loaded: %d screens, %d transitions from %s",
                     len(_screens), count, path)
        return count

    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load vision map: %s", e)
        return -1


def _load_v1(path: Path) -> int:
    """Load old ui_map.json (v1 format) and promote to v2."""
    global _total_observations, _total_predictions, _total_prediction_hits, _total_prediction_misses
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or data.get("version") != 1:
            return 0

        count = 0
        for screen_key, entries_list in data.get("entries", {}).items():
            # Create VisionScreen
            parts = screen_key.split("/", 1)
            pkg = parts[0] if parts else ""
            act = parts[1] if len(parts) > 1 else ""
            _screens[screen_key] = VisionScreen(
                screen_key=screen_key,
                package=pkg,
                activity=act,
                fingerprint=_screen_fingerprint(pkg, act),
            )

            for entry_data in entries_list:
                try:
                    # Map v1 fields to v2
                    t = ElementTransition(
                        screen_key=screen_key,
                        action=entry_data.get("action", ""),
                        from_element=entry_data.get("from_focused", ""),
                        to_element=entry_data.get("to_focused", ""),
                        to_screen_type=entry_data.get("to_screen_type", "unknown"),
                        to_screen_title=entry_data.get("to_screen_title", ""),
                        to_focused_position=entry_data.get("to_focused_position", ""),
                        to_focused_confidence=entry_data.get("to_focused_confidence", "low"),
                        to_navigation_path=entry_data.get("to_navigation_path", []),
                        observation_count=entry_data.get("observation_count", 0),
                        confidence=entry_data.get("confidence", 0.0),
                        last_observed=entry_data.get("last_observed", ""),
                        sources=["migrated_v1"],
                    )
                    _transitions[screen_key][(t.action, t.from_element)] = t
                    count += 1
                except Exception:
                    pass

        # Restore stats
        s = data.get("stats", {})
        _total_observations = s.get("total_observations", 0)
        _total_predictions = s.get("total_predictions", 0)
        _total_prediction_hits = s.get("total_prediction_hits", 0)
        _total_prediction_misses = s.get("total_prediction_misses", 0)
        _last_focused.update(data.get("last_focused", {}))

        return count

    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load old ui_map: %s", e)
        return 0


def save() -> int:
    """Save map to disk if dirty. Returns total transition count."""
    global _dirty
    if not _dirty:
        return sum(len(v) for v in _transitions.values())

    path = _map_path()
    tmp_path = path.with_suffix(".json.tmp")

    all_transitions = []
    for transitions in _transitions.values():
        for t in transitions.values():
            all_transitions.append(t.model_dump())

    data = {
        "version": _FORMAT_VERSION,
        "screens": {k: v.model_dump() for k, v in _screens.items()},
        "transitions": all_transitions,
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
        logger.info("Vision map saved: %d screens, %d transitions to %s",
                     len(_screens), len(all_transitions), path)
        return len(all_transitions)
    except OSError as e:
        logger.warning("Failed to save vision map: %s", e)
        return 0


# ── Navigation context ─────────────────────────────────────────────


def set_last_action(action: str) -> None:
    global _last_action
    _last_action = action


def get_last_action() -> str:
    return _last_action


def set_last_focused(screen_key: str, focused_label: str) -> None:
    global _dirty
    if focused_label:
        _last_focused[screen_key] = focused_label
        _dirty = True


def get_last_focused(screen_key: str) -> str:
    return _last_focused.get(screen_key, "")


# ── Observe ────────────────────────────────────────────────────────


def observe_transition(
    screen_key: str,
    action: str,
    from_element: str,
    to_element: str,
    to_screen_key: str = "",
    to_screen_type: str = "unknown",
    to_screen_title: str = "",
    to_focused_position: str = "",
    to_focused_confidence: str = "low",
    to_navigation_path: Optional[List[str]] = None,
    transition_ms: float = 0.0,
    source: str = "manual",
    vision: Optional[VisionAnalysis] = None,
) -> ElementTransition:
    """Single entry point for all writers. Creates or updates a transition."""
    global _total_observations, _dirty

    if vision:
        to_screen_type = vision.screen_type or to_screen_type
        to_screen_title = vision.screen_title or to_screen_title
        to_focused_position = vision.focused_position or to_focused_position
        to_focused_confidence = vision.focused_confidence or to_focused_confidence
        to_navigation_path = vision.navigation_path or to_navigation_path

    now = datetime.now(timezone.utc).isoformat()

    # Upsert screen
    _upsert_screen(screen_key, to_screen_type if not to_screen_key else "unknown",
                   to_screen_title if not to_screen_key else "", to_navigation_path)
    if to_screen_key and to_screen_key != screen_key:
        _upsert_screen(to_screen_key, to_screen_type, to_screen_title, to_navigation_path)

    # Upsert transition
    key = (action, from_element)
    transitions = _transitions[screen_key]
    existing = transitions.get(key)

    if existing and existing.to_element == to_element:
        # Same result — increment, boost confidence
        existing.observation_count += 1
        existing.confidence = _compute_confidence(existing.observation_count)
        existing.last_observed = now
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
        if to_screen_key:
            existing.to_screen_key = to_screen_key
        if transition_ms and existing.avg_transition_ms:
            existing.avg_transition_ms = (existing.avg_transition_ms + transition_ms) / 2
        elif transition_ms:
            existing.avg_transition_ms = transition_ms
        if source and source not in existing.sources:
            existing.sources.append(source)
        _total_observations += 1
        _dirty = True
        return existing

    # Different result or new entry
    if existing:
        logger.info("Vision map entry changed: %s/%s/%s: %s → %s (was %s)",
                     screen_key, action, from_element, from_element, to_element,
                     existing.to_element)

    entry = ElementTransition(
        screen_key=screen_key,
        action=action,
        from_element=from_element,
        to_element=to_element,
        to_screen_key=to_screen_key or "",
        to_screen_type=to_screen_type,
        to_screen_title=to_screen_title,
        to_focused_position=to_focused_position,
        to_focused_confidence=to_focused_confidence,
        to_navigation_path=to_navigation_path or [],
        observation_count=1,
        confidence=_compute_confidence(1),
        avg_transition_ms=transition_ms,
        last_observed=now,
        sources=[source] if source else [],
    )
    transitions[key] = entry
    _total_observations += 1
    _dirty = True
    return entry


def observe(**kwargs) -> ElementTransition:
    """Legacy compatibility wrapper — maps old ui_map.observe() field names."""
    mapped = dict(kwargs)
    if "from_focused" in mapped:
        mapped["from_element"] = mapped.pop("from_focused")
    if "to_focused" in mapped:
        mapped["to_element"] = mapped.pop("to_focused")
    return observe_transition(**mapped)


def _upsert_screen(
    screen_key: str,
    screen_type: str = "unknown",
    screen_title: str = "",
    navigation_path: Optional[List[str]] = None,
) -> None:
    """Create or update a VisionScreen."""
    parts = screen_key.split("/", 1)
    pkg = parts[0] if parts else ""
    act = parts[1] if len(parts) > 1 else ""

    existing = _screens.get(screen_key)
    if existing:
        existing.visit_count += 1
        existing.last_visited = datetime.now(timezone.utc).isoformat()
        if screen_type != "unknown":
            existing.screen_type = screen_type
        if screen_title:
            existing.screen_title = screen_title
        if navigation_path:
            existing.navigation_path = navigation_path
    else:
        _screens[screen_key] = VisionScreen(
            screen_key=screen_key,
            package=pkg,
            activity=act,
            screen_type=screen_type,
            screen_title=screen_title,
            navigation_path=navigation_path or [],
            visit_count=1,
            last_visited=datetime.now(timezone.utc).isoformat(),
            fingerprint=_screen_fingerprint(pkg, act),
        )


# ── Predict ────────────────────────────────────────────────────────


def predict(
    screen_key: str,
    action: str,
    from_element: str,
    min_confidence: float = 0.7,
    min_observations: int = 2,
) -> Optional[ElementTransition]:
    """Predict the result of an action. Returns None if no prediction."""
    global _total_predictions
    if not screen_key or not action or not from_element:
        return None

    transitions = _transitions.get(screen_key)
    if not transitions:
        return None

    entry = transitions.get((action, from_element))
    if entry is None:
        return None

    if entry.confidence < min_confidence or entry.observation_count < min_observations:
        return None

    _total_predictions += 1
    return entry


def validate(
    screen_key: str,
    action: str,
    from_element: str,
    actual_element: str,
) -> bool:
    """Validate a prediction. Returns True if correct."""
    global _total_prediction_hits, _total_prediction_misses, _dirty

    transitions = _transitions.get(screen_key)
    if not transitions:
        return False

    entry = transitions.get((action, from_element))
    if entry is None:
        return False

    if entry.to_element == actual_element:
        _total_prediction_hits += 1
        entry.observation_count += 1
        entry.confidence = _compute_confidence(entry.observation_count)
        entry.last_observed = datetime.now(timezone.utc).isoformat()
        _dirty = True
        return True

    _total_prediction_misses += 1
    entry.confidence = max(0.0, entry.confidence - 0.3)
    logger.warning("Vision map prediction wrong: %s/%s/%s predicted '%s' got '%s'",
                    screen_key, action, from_element, entry.to_element, actual_element)
    _dirty = True
    return False


# ── Fast path (nav counter) ───────────────────────────────────────

# These delegate to vision_cache for the nav-sequence fast path.
# Kept here so router only imports vision_map.

_nav_sequence: int = 0
_last_cache_hit_nav_seq: int = -1
_last_cache_result: Optional[VisionAnalysis] = None
_cache_hits: int = 0
_cache_misses: int = 0


def increment_nav() -> int:
    global _nav_sequence
    _nav_sequence += 1
    return _nav_sequence


def check_fast_path() -> Optional[VisionAnalysis]:
    global _cache_hits
    if _last_cache_result is not None and _nav_sequence == _last_cache_hit_nav_seq:
        _cache_hits += 1
        return _last_cache_result
    return None


def update_fast_path(analysis: VisionAnalysis) -> None:
    global _last_cache_hit_nav_seq, _last_cache_result
    _last_cache_hit_nav_seq = _nav_sequence
    _last_cache_result = analysis


def credit_map_hit() -> None:
    """Credit a map prediction as a cache hit."""
    global _cache_hits, _cache_misses
    _cache_hits += 1
    if _cache_misses > 0:
        _cache_misses -= 1


def cache_stats() -> dict:
    total = _cache_hits + _cache_misses
    return {
        "hits": _cache_hits,
        "misses": _cache_misses,
        "hit_ratio_pct": round(_cache_hits / total * 100, 1) if total > 0 else 0.0,
        "nav_sequence": _nav_sequence,
        "last_cache_hit_nav_seq": _last_cache_hit_nav_seq,
    }


# ── Pathfinding ────────────────────────────────────────────────────


def find_element_path(
    screen_key: str,
    from_element: str,
    to_element: str,
    min_confidence: float = 0.0,
) -> Optional[List[str]]:
    """BFS on element transitions within a screen.

    Returns list of actions (e.g. ["down", "down", "enter"]) or None.
    Low-confidence entries are included by default to maximize coverage.
    """
    transitions = _transitions.get(screen_key)
    if not transitions:
        return None

    if from_element == to_element:
        return []

    # Build adjacency: element -> [(action, next_element)]
    adj: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for (action, from_el), t in transitions.items():
        if t.confidence >= min_confidence:
            adj[from_el].append((action, t.to_element))

    # BFS
    queue: deque[Tuple[str, List[str]]] = deque([(from_element, [])])
    visited: Set[str] = {from_element}

    while queue:
        current, path = queue.popleft()
        for action, next_el in adj.get(current, []):
            if next_el == to_element:
                return path + [action]
            if next_el not in visited:
                visited.add(next_el)
                queue.append((next_el, path + [action]))

    return None


def find_screen_path(
    from_screen_key: str,
    to_screen_key: str,
) -> Optional[List[Tuple[str, str]]]:
    """BFS on cross-screen transitions.

    Returns list of (action, element_to_activate) tuples or None.
    """
    if from_screen_key == to_screen_key:
        return []

    # Build screen adjacency from "enter"/"back" transitions that change screen_key
    adj: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)  # screen -> [(action, element, target_screen)]
    for sk, transitions in _transitions.items():
        for (action, from_el), t in transitions.items():
            if t.to_screen_key and t.to_screen_key != sk:
                adj[sk].append((action, from_el, t.to_screen_key))

    # BFS
    queue: deque[Tuple[str, List[Tuple[str, str]]]] = deque([(from_screen_key, [])])
    visited: Set[str] = {from_screen_key}

    while queue:
        current, path = queue.popleft()
        for action, element, target in adj.get(current, []):
            if target == to_screen_key:
                return path + [(action, element)]
            if target not in visited:
                visited.add(target)
                queue.append((target, path + [(action, element)]))

    return None


# ── Query ──────────────────────────────────────────────────────────


def get_screen(screen_key: str) -> Optional[VisionScreen]:
    return _screens.get(screen_key)


def get_screen_entries(screen_key: str) -> List[ElementTransition]:
    transitions = _transitions.get(screen_key)
    if not transitions:
        return []
    return list(transitions.values())


def get_all_screens() -> List[dict]:
    screens = []
    for screen_key, screen in _screens.items():
        entries = _transitions.get(screen_key, {})
        entries_list = list(entries.values())
        avg_conf = sum(e.confidence for e in entries_list) / len(entries_list) if entries_list else 0
        screens.append({
            "screen_key": screen_key,
            "screen_type": screen.screen_type,
            "screen_title": screen.screen_title,
            "entry_count": len(entries_list),
            "avg_confidence": round(avg_conf, 2),
            "max_observations": max((e.observation_count for e in entries_list), default=0),
            "visit_count": screen.visit_count,
        })
    return screens


def items() -> List[Tuple[str, ElementTransition]]:
    """All transitions as (screen_key, entry) pairs."""
    result = []
    for sk, transitions in _transitions.items():
        for t in transitions.values():
            result.append((sk, t))
    return result


def stats() -> dict:
    total_entries = sum(len(v) for v in _transitions.values())
    pred_total = _total_predictions
    return {
        "total_screens": len(_screens),
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
    """Clear all data. Returns count cleared."""
    global _total_observations, _total_predictions, _total_prediction_hits
    global _total_prediction_misses, _dirty, _cache_hits, _cache_misses
    global _last_cache_hit_nav_seq, _last_cache_result
    count = sum(len(v) for v in _transitions.values())
    _screens.clear()
    _transitions.clear()
    _last_focused.clear()
    _total_observations = 0
    _total_predictions = 0
    _total_prediction_hits = 0
    _total_prediction_misses = 0
    _cache_hits = 0
    _cache_misses = 0
    _last_cache_hit_nav_seq = -1
    _last_cache_result = None
    _dirty = True
    return count
