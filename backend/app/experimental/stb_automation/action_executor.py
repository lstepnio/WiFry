"""STB_AUTOMATION — Key press execution with logcat-driven settle detection.

Sends a key event to the STB via ``adb_manager.send_key()`` and then
waits for the screen to settle using a tiered strategy:

  1. **Logcat events** (0-1000ms) — watch for ACTIVITY_DISPLAYED or
     FOCUS_CHANGED from the logcat monitor.  Fastest signal (~50-200ms).
  2. **dumpsys poll** (1000-2000ms) — fall back to polling
     ``dumpsys window windows`` for activity changes.
  3. **Activity fingerprint** (2000-3000ms) — compare activity-based
     fingerprint before/after to detect transitions.
  4. **Timeout** (3000ms) — record "no transition".

Hierarchy (uiautomator dump) is intentionally skipped during navigate
to avoid the ~3000ms penalty.  The background ``GET /state?vision=true``
call provides rich focus/element data via AI vision instead.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from ...services import adb_manager
from . import fingerprint as fp
from . import screen_reader
from .logcat_monitor import LogcatMonitor, get_monitor
from .models import LogcatEvent, ScreenState

logger = logging.getLogger("wifry.stb_automation.action_executor")


def _signals_dict(state: ScreenState) -> dict:
    """Extract ADB signal values for diagnostics."""
    return {
        "package": state.package,
        "activity": state.activity,
        "window_title": state.window_title,
        "fragments": state.fragments,
        "focused_element": (
            f"{state.focused_element.resource_id or state.focused_element.text or state.focused_element.class_name}"
            if state.focused_element else None
        ),
        "focused_context": state.focused_context,
        "ui_elements_count": len(state.ui_elements),
    }


@dataclass
class _SettleTiming:
    """Timing detail collected inside _settle()."""
    wait_ms: float = 0.0
    read_ms: float = 0.0
    read_detail: dict = field(default_factory=dict)


class NavigateResult:
    """Result of a navigate (key press + settle) operation."""

    __slots__ = (
        "action",
        "pre_state",
        "post_state",
        "pre_fingerprint",
        "post_fingerprint",
        "transitioned",
        "settle_method",
        "settle_ms",
        "timing",
    )

    def __init__(
        self,
        action: str,
        pre_state: ScreenState,
        post_state: ScreenState,
        pre_fingerprint: str,
        post_fingerprint: str,
        transitioned: bool,
        settle_method: str,
        settle_ms: float,
        timing: Optional[dict] = None,
    ):
        self.action = action
        self.pre_state = pre_state
        self.post_state = post_state
        self.pre_fingerprint = pre_fingerprint
        self.post_fingerprint = post_fingerprint
        self.transitioned = transitioned
        self.settle_method = settle_method
        self.settle_ms = settle_ms
        self.timing = timing

    def to_dict(self) -> dict:
        d = {
            "action": self.action,
            "pre_state": self.pre_state.model_dump(),
            "post_state": self.post_state.model_dump(),
            "pre_fingerprint": self.pre_fingerprint,
            "post_fingerprint": self.post_fingerprint,
            "transitioned": self.transitioned,
            "settle_method": self.settle_method,
            "settle_ms": round(self.settle_ms, 1),
        }
        if self.timing is not None:
            d["timing"] = self.timing
        return d


async def navigate(
    serial: str,
    action: str,
    settle_timeout_ms: int = 3000,
    monitor: Optional[LogcatMonitor] = None,
) -> NavigateResult:
    """Send a key press and wait for the screen to settle.

    Hierarchy (uiautomator dump) is skipped to avoid the ~3000ms
    penalty — the background GET /state?vision=true call provides
    rich focus/element data via AI vision instead.
    """
    if monitor is None:
        monitor = get_monitor()

    t_start = time.monotonic()

    # 1. Read pre-state (fast — dumpsys only, skip hierarchy)
    t0 = time.monotonic()
    pre_state, _ = await screen_reader.read_screen_state(
        serial, include_hierarchy=False,
    )
    pre_state_ms = round((time.monotonic() - t0) * 1000, 1)
    pre_fp = fp.fingerprint_from_activity(pre_state.package, pre_state.activity)

    # 2. Send key press
    t0 = time.monotonic()
    await adb_manager.send_key(serial, action)
    key_press_ms = round((time.monotonic() - t0) * 1000, 1)

    # 3. Settle detection — tiered strategy (no hierarchy)
    settle_method, post_state, settle_timing = await _settle(
        serial=serial,
        pre_package=pre_state.package,
        pre_activity=pre_state.activity,
        pre_fp=pre_fp,
        monitor=monitor,
        timeout_ms=settle_timeout_ms,
    )

    # 4. Post-fingerprint (activity-based, no hierarchy needed)
    t0 = time.monotonic()
    post_fp = fp.fingerprint_from_activity(post_state.package, post_state.activity)
    post_fingerprint_ms = round((time.monotonic() - t0) * 1000, 1)

    settle_ms = (time.monotonic() - t_start) * 1000
    transitioned = pre_fp != post_fp

    timing = {
        "pre_state_ms": pre_state_ms,
        "key_press_ms": key_press_ms,
        "settle_wait_ms": round(settle_timing.wait_ms, 1),
        "settle_read_ms": round(settle_timing.read_ms, 1),
        "settle_read_detail": settle_timing.read_detail,
        "post_fingerprint_ms": post_fingerprint_ms,
        "total_ms": round(settle_ms, 1),
        "signals": _signals_dict(post_state),
    }

    logger.info(
        "[STB_AUTOMATION] navigate(%s): %s -> %s (%s, %.0fms)",
        action,
        pre_fp[:8],
        post_fp[:8],
        settle_method,
        settle_ms,
    )

    return NavigateResult(
        action=action,
        pre_state=pre_state,
        post_state=post_state,
        pre_fingerprint=pre_fp,
        post_fingerprint=post_fp,
        transitioned=transitioned,
        settle_method=settle_method,
        settle_ms=settle_ms,
        timing=timing,
    )


def _read_timings_dict(timings: screen_reader.ReadTimings) -> dict:
    """Convert ReadTimings to a plain dict for the timing payload."""
    return {
        "foreground_ms": timings.foreground_ms,
        "hierarchy_ms": timings.hierarchy_ms,
        "fragments_ms": timings.fragments_ms,
        "window_title_ms": timings.window_title_ms,
        "total_ms": timings.total_ms,
    }


async def _settle(
    serial: str,
    pre_package: str,
    pre_activity: str,
    pre_fp: str,
    monitor: LogcatMonitor,
    timeout_ms: int,
) -> tuple[str, ScreenState, _SettleTiming]:
    """Tiered settle detection (no hierarchy).  Returns (method, post_state, timing)."""

    st = _SettleTiming()

    # Tier 1: Logcat events (up to 1000ms)
    if monitor.is_active:
        t_wait = time.monotonic()
        event = await monitor.wait_for_event(
            event_types=["ACTIVITY_DISPLAYED", "FOCUS_CHANGED"],
            timeout_ms=min(1000, timeout_ms),
        )
        if event is not None:
            # Event detected — short animation settle
            await asyncio.sleep(0.08)
            st.wait_ms = (time.monotonic() - t_wait) * 1000
            recent = monitor.get_events(last_n=5)
            t_read = time.monotonic()
            state, timings = await screen_reader.read_screen_state(
                serial, recent_events=recent, include_hierarchy=False,
            )
            st.read_ms = (time.monotonic() - t_read) * 1000
            st.read_detail = _read_timings_dict(timings)
            return "logcat", state, st
        st.wait_ms = (time.monotonic() - t_wait) * 1000
        # Logcat monitor is active but no event — skip dumpsys poll
        # (if logcat didn't see a transition, dumpsys won't either)

    else:
        # Tier 2: dumpsys poll — only when logcat monitor is NOT active
        tier2_deadline = min(2000, timeout_ms) / 1000.0
        tier2_start = time.monotonic()
        while (time.monotonic() - tier2_start) < tier2_deadline:
            pkg, act = await screen_reader.read_foreground_activity(serial)
            if pkg != pre_package or act != pre_activity:
                await asyncio.sleep(0.08)
                st.wait_ms += (time.monotonic() - tier2_start) * 1000
                recent = []
                t_read = time.monotonic()
                state, timings = await screen_reader.read_screen_state(
                    serial, recent_events=recent, include_hierarchy=False,
                )
                st.read_ms = (time.monotonic() - t_read) * 1000
                st.read_detail = _read_timings_dict(timings)
                return "dumpsys", state, st
            await asyncio.sleep(0.05)
        st.wait_ms += (time.monotonic() - tier2_start) * 1000

    # Tier 3: Activity fingerprint comparison (no hierarchy)
    recent = monitor.get_events(last_n=5) if monitor.is_active else []
    t_read = time.monotonic()
    state, timings = await screen_reader.read_screen_state(
        serial, recent_events=recent, include_hierarchy=False,
    )
    st.read_ms = (time.monotonic() - t_read) * 1000
    st.read_detail = _read_timings_dict(timings)
    post_fp = fp.fingerprint_from_activity(state.package, state.activity)
    if post_fp != pre_fp:
        return "activity", state, st

    # Tier 4: Timeout — no transition detected
    return "timeout", state, st


async def navigate_mock(action: str) -> NavigateResult:
    """Mock navigate for dev/mock mode."""
    pre = screen_reader.mock_screen_state()
    pre_fp = fp.fingerprint(pre)

    # Simulate a transition for "enter" and "back"
    post = screen_reader.mock_screen_state()
    if action == "enter":
        post.activity = "com.example.stb/.DetailActivity"
        post.package = "com.example.stb"
    elif action == "back":
        post.activity = "com.example.stb/.HomeActivity"

    post_fp = fp.fingerprint(post)
    return NavigateResult(
        action=action,
        pre_state=pre,
        post_state=post,
        pre_fingerprint=pre_fp,
        post_fingerprint=post_fp,
        transitioned=pre_fp != post_fp,
        settle_method="mock",
        settle_ms=150.0,
        timing={
            "pre_state_ms": 0,
            "key_press_ms": 0,
            "settle_wait_ms": 0,
            "settle_read_ms": 0,
            "settle_read_detail": {},
            "post_fingerprint_ms": 0,
            "total_ms": 150.0,
            "signals": _signals_dict(post),
        },
    )
