"""Vision cache with disk persistence.

In-memory OrderedDict for O(1) lookups, persisted to JSON on shutdown
and loaded on startup.  All cache state is isolated here so the
backing store can be swapped to Redis/SQLite in the future by changing
only this module.

Cache keys are content-addressed (frame hash) and device-agnostic,
so a future shared cache naturally deduplicates across devices.
"""

import json
import logging
import os
from collections import OrderedDict
from pathlib import Path
from typing import List, Optional, Tuple

from ...config import settings
from ...services import storage
from .models import VisionAnalysis

logger = logging.getLogger("wifry.stb_automation.vision_cache")

_CACHE_FILE = "vision_cache.json"
_FORMAT_VERSION = 1

# ── In-memory state ────────────────────────────────────────────────

_cache: OrderedDict[str, VisionAnalysis] = OrderedDict()

# Navigation counter — fast-path: if no navigation happened since
# the last cache hit, skip hash computation entirely.
_nav_sequence: int = 0
_last_cache_hit_nav_seq: int = -1
_last_cache_result: Optional[VisionAnalysis] = None

# Hit/miss counters
_hits: int = 0
_misses: int = 0

# Dirty flag — only write to disk when cache has changed
_dirty: bool = False


# ── Persistence ────────────────────────────────────────────────────


def _cache_path() -> Path:
    return storage.ensure_data_path("runtime_state") / _CACHE_FILE


def load() -> int:
    """Load cache from disk.  Returns number of entries loaded.

    Safe to call at any time — corrupt or missing files result in an
    empty cache with a warning log (no exception raised).
    """
    global _dirty
    path = _cache_path()
    if not path.exists():
        return 0

    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or data.get("version") != _FORMAT_VERSION:
            logger.warning("Vision cache file has unknown format, starting fresh")
            return 0

        entries = data.get("entries", [])
        count = 0
        for entry in entries:
            key = entry.get("key")
            analysis_data = entry.get("analysis")
            if key and analysis_data:
                try:
                    _cache[key] = VisionAnalysis.model_validate(analysis_data)
                    count += 1
                except Exception:
                    pass  # skip corrupt entries

        # Evict if over max (file could be from a config with higher max)
        max_entries = settings.stb_vision_cache_max
        while len(_cache) > max_entries:
            _cache.popitem(last=False)

        _dirty = False
        logger.info("Vision cache loaded: %d entries from %s", count, path)
        return count

    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load vision cache: %s", e)
        return 0


def save() -> int:
    """Save cache to disk if dirty.  Returns number of entries saved.

    Uses atomic write (write to .tmp, then os.replace) to avoid
    corruption on crash/power loss.
    """
    global _dirty
    if not _dirty:
        return len(_cache)

    path = _cache_path()
    tmp_path = path.with_suffix(".json.tmp")

    entries = [
        {"key": key, "analysis": analysis.model_dump()}
        for key, analysis in _cache.items()
    ]
    data = {"version": _FORMAT_VERSION, "entries": entries}

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(json.dumps(data, separators=(",", ":")))
        os.replace(str(tmp_path), str(path))
        _dirty = False
        logger.info("Vision cache saved: %d entries to %s", len(entries), path)
        return len(entries)
    except OSError as e:
        logger.warning("Failed to save vision cache: %s", e)
        return 0


# ── Lookup ─────────────────────────────────────────────────────────


def get(key: str) -> Optional[VisionAnalysis]:
    """O(1) lookup by frame hash.  Returns None on miss."""
    global _hits, _misses
    if key in _cache:
        _cache.move_to_end(key)
        _hits += 1
        return _cache[key]
    _misses += 1
    return None


def credit_map_hit() -> None:
    """Credit a UI map prediction as a cache hit.

    Called by the router when the UI map handles a request that the
    vision cache missed.  Corrects the hit/miss ratio to reflect
    the overall 'avoided AI call' rate.
    """
    global _hits, _misses
    _hits += 1
    if _misses > 0:
        _misses -= 1


def put(key: str, analysis: VisionAnalysis) -> None:
    """Store an entry, evict LRU if over max."""
    global _dirty
    _cache[key] = analysis
    _cache.move_to_end(key)
    max_entries = settings.stb_vision_cache_max
    while len(_cache) > max_entries:
        _cache.popitem(last=False)
    _dirty = True


# ── Navigation counter (fast-path) ────────────────────────────────


def increment_nav() -> int:
    """Increment nav sequence.  Returns new value."""
    global _nav_sequence
    _nav_sequence += 1
    return _nav_sequence


def check_fast_path() -> Optional[VisionAnalysis]:
    """Return cached result if nav_sequence unchanged since last hit."""
    global _hits
    if (
        _last_cache_result is not None
        and _nav_sequence == _last_cache_hit_nav_seq
    ):
        _hits += 1
        return _last_cache_result
    return None


def update_fast_path(analysis: VisionAnalysis) -> None:
    """Update fast-path state after a cache hit or fresh analysis."""
    global _last_cache_hit_nav_seq, _last_cache_result
    _last_cache_hit_nav_seq = _nav_sequence
    _last_cache_result = analysis


# ── Diagnostics ────────────────────────────────────────────────────


def stats() -> dict:
    """Return cache statistics for diagnostics."""
    total = _hits + _misses
    return {
        "size": len(_cache),
        "max_size": settings.stb_vision_cache_max,
        "hits": _hits,
        "misses": _misses,
        "hit_ratio_pct": round(_hits / total * 100, 1) if total > 0 else 0.0,
        "nav_sequence": _nav_sequence,
        "last_cache_hit_nav_seq": _last_cache_hit_nav_seq,
    }


def items() -> List[Tuple[str, VisionAnalysis]]:
    """Return all cache entries (for debug endpoint)."""
    return list(_cache.items())


def clear() -> int:
    """Clear all entries.  Returns count cleared."""
    global _last_cache_hit_nav_seq, _last_cache_result, _hits, _misses, _dirty
    count = len(_cache)
    _cache.clear()
    _last_cache_hit_nav_seq = -1
    _last_cache_result = None
    _hits = 0
    _misses = 0
    _dirty = True
    return count
