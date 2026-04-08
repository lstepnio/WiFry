"""STB_AUTOMATION — Screen fingerprinting for navigation graph identity.

Two fingerprint levels:

  1. ``fingerprint()`` — **stable** screen identity for the navigation graph.
     Based on package/activity + structural skeleton (class names + resource
     IDs).  Does NOT change when you scroll a list or different text appears.

  2. ``visual_hash()`` — **volatile** hash of everything visible on screen.
     Includes text, bounds, focused/selected state, content_desc.  Changes
     every time the focused element moves or any text changes.  Used for
     vision cache invalidation.

On NAF-heavy STBs (TiVo, etc.) where class_name and resource_id are
mostly empty, the stable fingerprint degrades to package/activity alone.
The visual_hash still differentiates screens via bounds + focused state.
"""

import hashlib
from typing import List

from .models import ScreenState, UIElement


def fingerprint(state: ScreenState) -> str:
    """Compute a 12-char hex screen fingerprint (stable identity)."""
    structural_hash = _structural_hash(state.ui_elements)
    composite = f"{state.package}/{state.activity}:{structural_hash}"
    return hashlib.sha256(composite.encode()).hexdigest()[:12]


def visual_hash(state: ScreenState) -> str:
    """Compute a 12-char hex visual hash (volatile — changes with focus/text).

    Used for vision cache invalidation.  Includes everything the user
    can see: text, bounds, focused state, content_desc.
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
