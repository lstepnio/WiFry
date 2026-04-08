"""STB_AUTOMATION — Screen fingerprinting for navigation graph identity.

Three fingerprint levels:

  1. ``fingerprint()`` — **stable** screen identity for the navigation graph.
     Based on package/activity + structural skeleton (class names + resource
     IDs).  Does NOT change when you scroll a list or different text appears.

  2. ``visual_hash()`` — **volatile** hash of ADB UI element data.
     Includes text, bounds, focused/selected state, content_desc.  Changes
     when the accessibility tree updates — but on NAF-heavy STBs like TiVo,
     the tree may NOT update when focus moves (highlight is purely visual).

  3. ``frame_hash()`` — **pixel-level** hash of the actual HDMI frame.
     Always changes when anything visible changes.  Used as the ultimate
     vision cache key when ADB-based hashes prove static.

On NAF-heavy STBs (TiVo, etc.) where class_name, resource_id, text,
focused, and selected are all empty/static, ``visual_hash`` degrades to
the same value across screens.  ``frame_hash`` is the fallback.
"""

import hashlib
from typing import List, Optional

from .models import ScreenState, UIElement


def fingerprint(state: ScreenState) -> str:
    """Compute a 12-char hex screen fingerprint (stable identity)."""
    structural_hash = _structural_hash(state.ui_elements)
    composite = f"{state.package}/{state.activity}:{structural_hash}"
    return hashlib.sha256(composite.encode()).hexdigest()[:12]


def visual_hash(state: ScreenState) -> str:
    """Compute a 12-char hex visual hash (volatile — changes with focus/text).

    Used for vision cache invalidation on devices where uiautomator
    reports focus/text changes.  Falls through to frame_hash on NAF STBs.
    """
    parts = []
    for el in state.ui_elements:
        parts.append(
            f"{el.class_name}|{el.resource_id}|{el.text}|{el.content_desc}"
            f"|{el.bounds}|{el.focused}|{el.selected}"
        )
    skeleton = "\n".join(parts)
    composite = f"{state.package}/{state.activity}:{skeleton}"
    return hashlib.sha256(composite.encode()).hexdigest()[:12]


def frame_hash(frame_jpeg: Optional[bytes]) -> str:
    """Compute a 12-char hex hash of the raw HDMI frame bytes.

    This is the ultimate cache key — it ALWAYS changes when anything
    visible on screen changes, regardless of whether the accessibility
    tree reports it.  Used for vision cache invalidation on NAF-heavy
    STBs where visual_hash never changes.

    Returns empty string if no frame is available.
    """
    if not frame_jpeg:
        return ""
    return hashlib.sha256(frame_jpeg).hexdigest()[:12]


def _structural_hash(elements: List[UIElement]) -> str:
    """Hash the UI hierarchy skeleton.

    Uses only class_name and resource_id — ignoring text and bounds
    so that content changes don't change the fingerprint.
    """
    parts = []
    for el in elements:
        parts.append(f"{el.class_name}|{el.resource_id}")
    skeleton = "\n".join(parts)
    return hashlib.sha256(skeleton.encode()).hexdigest()[:16]


def fingerprint_from_activity(package: str, activity: str) -> str:
    """Quick fingerprint from just package/activity (no hierarchy).

    Useful when we only have dumpsys output and want a fast identifier
    for settle detection.
    """
    composite = f"{package}/{activity}:"
    return hashlib.sha256(composite.encode()).hexdigest()[:12]
