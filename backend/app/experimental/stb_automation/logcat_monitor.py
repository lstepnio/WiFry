"""STB_AUTOMATION — Logcat event monitor for STB state transitions.

Wraps ``adb_manager.start_logcat()`` with STB-relevant tag filters and
parses raw logcat lines into typed ``LogcatEvent`` objects.  The monitor
maintains a small event queue (last 50 events) that the crawl engine,
action executor, and anomaly detector can consume.

No new subprocess management — all logcat I/O goes through
``adb_manager``'s existing session infrastructure.
"""

import asyncio
import logging
import re
from collections import deque
from datetime import datetime, timezone
from typing import Deque, List, Optional

from ...services import adb_manager
from .models import LogcatEvent

logger = logging.getLogger("wifry.stb_automation.logcat_monitor")

MAX_EVENTS = 50

# Default logcat tag filters — only activity/window lifecycle events
DEFAULT_TAGS = ["ActivityManager:I", "WindowManager:I"]

# Patterns for event extraction from logcat messages
_EVENT_PATTERNS = [
    # ActivityManager: Displayed com.foo/.BarActivity: +500ms
    (
        "ACTIVITY_DISPLAYED",
        re.compile(
            r"Displayed\s+(\S+?)/(\S+?)(?:\s|:|\+|$)"
        ),
    ),
    # ActivityManager: ... resumed com.foo/.BarActivity
    # ActivityManager: Resume activity: ... com.foo/.BarActivity
    (
        "ACTIVITY_RESUMED",
        re.compile(
            r"(?:resumed?|Resum\w+\s+activity).*?(\S+?)/(\S+?)(?:\s|$)"
        ),
    ),
    # ActivityManager: Pausing activity com.foo/.BarActivity
    (
        "ACTIVITY_PAUSED",
        re.compile(
            r"Paus\w+\s+activity.*?(\S+?)/(\S+?)(?:\s|$)"
        ),
    ),
    # WindowManager: Focus changing ... -> com.foo/com.foo.BarActivity
    (
        "FOCUS_CHANGED",
        re.compile(
            r"Focus\s+chang\w+.*?(\S+?)/(\S+?)(?:\s|\}|$)"
        ),
    ),
]


class LogcatMonitor:
    """STB_AUTOMATION — Monitors logcat for UI state transitions."""

    def __init__(self) -> None:
        self._session_id: Optional[str] = None
        self._serial: Optional[str] = None
        self._events: Deque[LogcatEvent] = deque(maxlen=MAX_EVENTS)
        self._poll_task: Optional[asyncio.Task] = None
        self._running = False
        # Tracks the last logcat line count we processed
        self._last_line_count = 0

    @property
    def is_active(self) -> bool:
        return self._running and self._session_id is not None

    @property
    def serial(self) -> Optional[str]:
        return self._serial

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    async def start(
        self,
        serial: str,
        tags: Optional[List[str]] = None,
    ) -> str:
        """Start monitoring logcat on the given device.

        Returns the logcat session ID.
        """
        if self._running:
            await self.stop()

        filters = tags or DEFAULT_TAGS
        # For the monitor we also want unfiltered lines for anomaly
        # detection later.  Start without *:S so we get everything,
        # but we parse only the events we care about.
        session = await adb_manager.start_logcat(
            serial=serial,
            filters=filters,
        )
        self._session_id = session.id
        self._serial = serial
        self._running = True
        self._last_line_count = 0
        self._events.clear()

        # Start polling logcat buffer for new lines
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(
            "[STB_AUTOMATION] Logcat monitor started: session=%s serial=%s",
            session.id,
            serial,
        )
        return session.id

    async def stop(self) -> None:
        """Stop monitoring and clean up the logcat session."""
        self._running = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

        if self._session_id:
            try:
                await adb_manager.stop_logcat(self._session_id)
            except (ValueError, Exception) as e:
                logger.debug("Error stopping logcat session %s: %s", self._session_id, e)
            self._session_id = None

        self._serial = None
        logger.info("[STB_AUTOMATION] Logcat monitor stopped")

    def get_events(self, last_n: int = 20) -> List[LogcatEvent]:
        """Return the most recent events (newest last)."""
        events = list(self._events)
        return events[-last_n:]

    async def wait_for_event(
        self,
        event_types: Optional[List[str]] = None,
        timeout_ms: int = 3000,
    ) -> Optional[LogcatEvent]:
        """Wait for a matching logcat event within timeout.

        Returns the first matching event, or None on timeout.
        Used by settle detection after key press.
        """
        target_types = set(event_types or ["ACTIVITY_DISPLAYED", "FOCUS_CHANGED"])
        deadline = asyncio.get_event_loop().time() + (timeout_ms / 1000.0)
        baseline = len(self._events)

        while asyncio.get_event_loop().time() < deadline:
            # Check for new events since baseline
            current = list(self._events)
            for ev in current[baseline:]:
                if ev.event_type in target_types:
                    return ev
            baseline = len(current)
            await asyncio.sleep(0.05)  # 50ms poll

        return None

    async def _poll_loop(self) -> None:
        """Background task: periodically read new logcat lines and parse events."""
        try:
            while self._running and self._session_id:
                lines = adb_manager.get_logcat_lines(
                    self._session_id,
                    last_n=100,
                )
                # Process only lines we haven't seen yet
                new_lines = lines[self._last_line_count:] if self._last_line_count < len(lines) else []
                self._last_line_count = len(lines)

                for line in new_lines:
                    event = _parse_logcat_event(line.tag, line.message, line.timestamp, line.raw)
                    if event:
                        self._events.append(event)

                await asyncio.sleep(0.1)  # 100ms poll interval
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("[STB_AUTOMATION] Logcat monitor poll error")


def _parse_logcat_event(
    tag: str,
    message: str,
    timestamp: str,
    raw: str,
) -> Optional[LogcatEvent]:
    """Try to extract a structured event from a logcat line."""
    for event_type, pattern in _EVENT_PATTERNS:
        m = pattern.search(message)
        if m:
            return LogcatEvent(
                event_type=event_type,
                package=m.group(1),
                activity=m.group(2) if m.lastindex and m.lastindex >= 2 else "",
                detail=message.strip(),
                timestamp=timestamp,
                raw=raw,
            )
    return None


# Module-level singleton
_monitor = LogcatMonitor()


def get_monitor() -> LogcatMonitor:
    """Return the module-level LogcatMonitor singleton."""
    return _monitor
