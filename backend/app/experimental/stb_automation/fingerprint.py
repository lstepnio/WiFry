"""STB_AUTOMATION — Screen fingerprinting for navigation graph identity.

Produces a 12-character hex ID for a screen state based on a composite
of ADB signals:

  1. ``package/activity`` from dumpsys
  2. Structural hash of the UI hierarchy skeleton (class names +
     resource IDs — NOT text or bounds, which change with content)

The fingerprint is stable across content changes (e.g. different movie
titles on the same home screen) but distinguishes structurally different
screens (e.g. home vs settings).
"""

import hashlib
from typing import List

from .models import ScreenState, UIElement


def fingerprint(state: ScreenState) -> str:
    """Compute a 12-char hex screen fingerprint."""
    structural_hash = _structural_hash(state.ui_elements)
    composite = f"{state.package}/{state.activity}:{structural_hash}"
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
