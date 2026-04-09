"""STB_AUTOMATION — Screen fingerprinting for navigation graph identity.

Three fingerprint levels:

  1. ``fingerprint()`` — **stable** screen identity for the navigation graph.
     Based on package/activity + structural skeleton (class names + resource
     IDs).  Does NOT change when you scroll a list or different text appears.

  2. ``visual_hash()`` — **volatile** hash of ADB UI element data.
     Includes text, bounds, focused/selected state, content_desc.  Changes
     when the accessibility tree updates — but on NAF-heavy STBs like TiVo,
     the tree may NOT update when focus moves (highlight is purely visual).

  3. ``frame_hash()`` — **perceptual hash** of the HDMI frame.
     Uses dHash (difference hash) from the ``imagehash`` library on a
     center-cropped frame.  Tolerant of JPEG compression noise (Hamming
     distance 0-2) but detects real screen changes (distance 15+).
     Center-crop removes 10% edges to ignore clock/status bar updates.

     Falls back to SHA-256 prefixed with ``sha256:`` when imagehash/Pillow
     are not installed.

On NAF-heavy STBs (TiVo, etc.) where class_name, resource_id, text,
focused, and selected are all empty/static, ``visual_hash`` degrades to
the same value across screens.  ``frame_hash`` is the fallback.
"""

import hashlib
import io
import logging
from typing import List, Optional

from .models import ScreenState, UIElement

logger = logging.getLogger("wifry.stb_automation.fingerprint")

# Conditional import for perceptual hashing
_HAS_IMAGEHASH = False
try:
    import imagehash
    from PIL import Image

    _HAS_IMAGEHASH = True
except ImportError:
    logger.info("imagehash/Pillow not installed — falling back to SHA-256 frame hash")


# dHash parameters
_HASH_SIZE = 12  # 144-bit hash (12×12 gradient grid)
_CROP_MARGIN = 0.10  # 10% off each edge


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
    """Compute a perceptual hash of the HDMI frame.

    Uses dHash (difference hash) on a center-cropped frame:
    - Center-crop: removes 10% from each edge (ignores clock/status bar)
    - dHash with hash_size=12: 144-bit hash as 36-char hex string
    - Tolerates JPEG compression noise (Hamming distance 0-2)
    - Detects real changes (highlight moved: distance 15+)

    Returns ``sha256:<hex>`` fallback if imagehash/Pillow are not installed.
    Returns empty string if no frame is available.
    """
    if not frame_jpeg:
        return ""

    if _HAS_IMAGEHASH:
        try:
            img = Image.open(io.BytesIO(frame_jpeg))
            # Center-crop: remove 10% from each edge
            iw, ih = img.size
            left = int(iw * _CROP_MARGIN)
            top = int(ih * _CROP_MARGIN)
            right = int(iw * (1 - _CROP_MARGIN))
            bottom = int(ih * (1 - _CROP_MARGIN))
            cropped = img.crop((left, top, right, bottom))
            dhash = imagehash.dhash(cropped, hash_size=_HASH_SIZE)
            return str(dhash)
        except Exception as e:
            logger.warning("Perceptual hash failed, falling back to SHA-256: %s", e)

    # SHA-256 fallback (prefixed so we can distinguish in distance calc)
    return f"sha256:{hashlib.sha256(frame_jpeg).hexdigest()[:24]}"


def frame_hash_distance(a: str, b: str) -> int:
    """Compute Hamming distance between two frame hashes.

    Returns the number of differing bits between two perceptual hashes.
    - Distance 0-2: same screen (JPEG noise)
    - Distance 6: configured threshold default
    - Distance 15+: different screen position
    - Distance 40+: entirely different screen

    Returns 999 for incompatible hashes (SHA-256 fallback, empty, mixed).
    """
    if not a or not b:
        return 999
    if a.startswith("sha256:") or b.startswith("sha256:"):
        # SHA-256 hashes: exact match only
        return 0 if a == b else 999
    if not _HAS_IMAGEHASH:
        return 999

    try:
        hash_a = imagehash.hex_to_hash(a)
        hash_b = imagehash.hex_to_hash(b)
        return hash_a - hash_b
    except Exception:
        return 999


def has_perceptual_hash() -> bool:
    """Return True if perceptual hashing (imagehash) is available."""
    return _HAS_IMAGEHASH


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
