"""STB_AUTOMATION — Anomaly detection from logcat and vision signals.

Runs alongside any execution mode (crawl, chaos, replay).  Two channels:

  1. **Logcat patterns** — regex matching on logcat lines for ANR, crash,
     OOM, media errors, network errors, permission denials.
  2. **Vision anomaly detection** — periodic HDMI frame checks for stuck
     UI, error dialogs, black screens (Phase 1G, stubbed here).

On anomaly detection, triggers automatic diagnostic collection via
``diagnostics.py``.
"""

import logging
import re
from collections import deque
from datetime import datetime, timezone
from typing import Deque, List, Optional

from .models import AnomalyPattern, DetectedAnomaly, LogcatEvent

logger = logging.getLogger("wifry.stb_automation.anomaly_detector")

MAX_ANOMALIES = 200

# Default anomaly patterns for Android STBs
DEFAULT_PATTERNS: List[AnomalyPattern] = [
    AnomalyPattern(
        name="anr",
        pattern=r"ANR in\s+(\S+)",
        tags=["ActivityManager"],
        severity="critical",
        category="crash",
    ),
    AnomalyPattern(
        name="crash",
        pattern=r"FATAL EXCEPTION",
        tags=["AndroidRuntime"],
        severity="critical",
        category="crash",
    ),
    AnomalyPattern(
        name="oom",
        pattern=r"(?:lowmemorykiller|Out of memory|OOM)",
        severity="high",
        category="memory",
    ),
    AnomalyPattern(
        name="media_error",
        pattern=r"(?:MediaPlayer.*[Ee]rror|ExoPlayer.*error|MediaCodec.*error)",
        severity="high",
        category="media",
    ),
    AnomalyPattern(
        name="network_error",
        pattern=r"(?:Network unreachable|Connection refused|Connection timed out|UnknownHostException)",
        severity="medium",
        category="network",
    ),
    AnomalyPattern(
        name="permission_denied",
        pattern=r"Permission denial",
        severity="medium",
        category="permission",
    ),
]


class AnomalyDetector:
    """STB_AUTOMATION — Detects anomalies from logcat events."""

    def __init__(self) -> None:
        self._patterns: List[AnomalyPattern] = list(DEFAULT_PATTERNS)
        self._compiled: List[tuple[AnomalyPattern, re.Pattern]] = []
        self._anomalies: Deque[DetectedAnomaly] = deque(maxlen=MAX_ANOMALIES)
        self._recompile()

    def _recompile(self) -> None:
        """Compile regex patterns."""
        self._compiled = []
        for p in self._patterns:
            try:
                self._compiled.append((p, re.compile(p.pattern, re.IGNORECASE)))
            except re.error as e:
                logger.warning("[STB_AUTOMATION] Bad anomaly pattern '%s': %s", p.name, e)

    @property
    def patterns(self) -> List[AnomalyPattern]:
        return list(self._patterns)

    def set_patterns(self, patterns: List[AnomalyPattern]) -> None:
        """Replace the anomaly patterns."""
        self._patterns = list(patterns)
        self._recompile()

    def get_anomalies(self, last_n: int = 50) -> List[DetectedAnomaly]:
        """Return the most recent anomalies."""
        items = list(self._anomalies)
        return items[-last_n:]

    def clear_anomalies(self) -> None:
        self._anomalies.clear()

    def check_event(
        self,
        event: LogcatEvent,
        context_lines: Optional[List[str]] = None,
    ) -> Optional[DetectedAnomaly]:
        """Check a logcat event against all anomaly patterns.

        Returns a DetectedAnomaly if matched, or None.
        """
        text = event.raw or event.detail

        for pattern, compiled in self._compiled:
            # Tag filter: if pattern specifies tags, event tag must match
            if pattern.tags:
                tag_match = any(
                    t.lower() in event.raw.lower() for t in pattern.tags
                )
                if not tag_match:
                    continue

            if compiled.search(text):
                anomaly = DetectedAnomaly(
                    pattern_name=pattern.name,
                    severity=pattern.severity,
                    category=pattern.category,
                    timestamp=event.timestamp or datetime.now(timezone.utc).isoformat(),
                    logcat_line=event,
                    context_lines=context_lines or [],
                )
                self._anomalies.append(anomaly)
                logger.warning(
                    "[STB_AUTOMATION] Anomaly detected: %s (%s) — %s",
                    pattern.name, pattern.severity, text[:120],
                )
                return anomaly

        return None

    def check_events(
        self,
        events: List[LogcatEvent],
        context_lines: Optional[List[str]] = None,
    ) -> List[DetectedAnomaly]:
        """Check a batch of events.  Returns all detected anomalies."""
        detected = []
        for ev in events:
            anomaly = self.check_event(ev, context_lines)
            if anomaly:
                detected.append(anomaly)
        return detected


# Module-level singleton
_detector = AnomalyDetector()


def get_detector() -> AnomalyDetector:
    """Return the module-level AnomalyDetector singleton."""
    return _detector
