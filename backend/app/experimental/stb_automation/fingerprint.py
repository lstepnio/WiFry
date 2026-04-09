"""STB_AUTOMATION — Screen fingerprinting for navigation graph identity.

Three fingerprint levels:

  1. ``fingerprint()`` — **stable** screen identity for the navigation graph.
     Based on package/activity + structural skeleton (class names + resource
     IDs).  Does NOT change when you scroll a list or different text appears.

  2. ``visual_hash()`` — **volatile** hash of ADB UI element data.
     Includes text, bounds, focused/selected state, content_desc.  Changes
     when the accessibility tree updates — but on NAF-heavy STBs like TiVo,
     the tree may NOT update when focus moves (highlight is purely visual).

  3. ``frame_hash()`` — **quantized downscale hash** of the HDMI frame.
     Decodes JPEG → center-crop → resize to 64×48 → quantize pixel values
     (divide by 8, rounding away JPEG compression noise) → SHA-256.

     This produces an **exact-match hash**: two JPEG captures of the same
     screen always produce the same hash (JPEG noise is quantized away),
     while even small visual changes (highlight shift) produce a completely
     different hash.  No Hamming distance / fuzzy matching needed.

     Falls back to SHA-256 of raw JPEG bytes prefixed with ``sha256:``
     when Pillow is not installed.

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

# Conditional import for image processing
_HAS_PIL = False
try:
    from PIL import Image
    import numpy as np

    _HAS_PIL = True
except ImportError:
    logger.info("Pillow/numpy not installed — falling back to raw SHA-256 frame hash")


# Quantized downscale parameters
_DOWNSCALE_SIZE = (64, 48)  # Small enough to smooth noise, large enough to capture detail
_QUANT_DIVISOR = 8  # Quantize pixel values: 256 levels → 32 levels per channel
_CROP_MARGIN = 0.10  # 10% off each edge (removes clock/status bar)


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
    """Compute a quantized downscale hash of the HDMI frame.

    Pipeline:
      1. Decode JPEG → PIL Image
      2. Center-crop 10% edges (removes clock/status bar)
      3. Resize to 64×48 (each pixel averages ~20×15 original pixels)
      4. Quantize: integer-divide each pixel channel by 8 (256→32 levels)
      5. SHA-256 of the quantized pixel bytes → 16 hex chars

    This is an **exact-match** hash — no fuzzy/Hamming distance needed:
    - Two JPEG encodes of the same screen → identical hash (noise quantized away)
    - Highlight bar shift → completely different hash (dozens of pixels change by 50+)
    - Clock tick in cropped edge → no effect (cropped out)

    Returns ``sha256:<raw-hex>`` fallback if Pillow is not installed.
    Returns empty string if no frame is available.
    """
    if not frame_jpeg:
        return ""

    if _HAS_PIL:
        try:
            img = Image.open(io.BytesIO(frame_jpeg))
            # Center-crop: remove 10% from each edge
            iw, ih = img.size
            left = int(iw * _CROP_MARGIN)
            top = int(ih * _CROP_MARGIN)
            right = int(iw * (1 - _CROP_MARGIN))
            bottom = int(ih * (1 - _CROP_MARGIN))
            cropped = img.crop((left, top, right, bottom))

            # Downscale — averages pixel blocks, smoothing JPEG noise
            small = cropped.resize(_DOWNSCALE_SIZE, Image.LANCZOS)

            # Quantize — rounds away remaining noise
            arr = np.array(small, dtype=np.uint8)
            quantized = (arr // _QUANT_DIVISOR).tobytes()

            return hashlib.sha256(quantized).hexdigest()[:16]
        except Exception as e:
            logger.warning("Quantized hash failed, falling back to raw SHA-256: %s", e)

    # Raw SHA-256 fallback (prefixed so we can distinguish)
    return f"sha256:{hashlib.sha256(frame_jpeg).hexdigest()[:24]}"


def frame_hash_distance(a: str, b: str) -> int:
    """Compute distance between two frame hashes.

    With quantized downscale hashing, this is binary: 0 (exact match) or
    999 (different).  There is no meaningful Hamming distance — the hash
    is a SHA-256 digest, not a perceptual hash.

    This function exists for API compatibility with the cache lookup code.
    """
    if not a or not b:
        return 999
    return 0 if a == b else 999


def has_perceptual_hash() -> bool:
    """Return True if image-based hashing (Pillow) is available."""
    return _HAS_PIL


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
