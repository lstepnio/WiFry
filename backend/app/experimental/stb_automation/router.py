"""STB_AUTOMATION — FastAPI router for STB test automation.

Phase 1A endpoints:
  GET  /api/v1/experimental/stb/status  — Overall automation status
  GET  /api/v1/experimental/stb/state   — Current screen state via ADB
  GET  /api/v1/experimental/stb/events  — Recent logcat events

Phase 1B endpoints:
  POST /api/v1/experimental/stb/navigate — Send key + observe result

All endpoints return 404 if the feature flag is disabled.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ...config import settings
from ...services import feature_flags
from . import action_executor, fingerprint as fp, screen_reader
from .logcat_monitor import get_monitor
from .models import CrawlStatus, LogcatEvent, ScreenState

logger = logging.getLogger("wifry.stb_automation.router")

router = APIRouter(
    prefix="/api/v1/experimental/stb",
    tags=["stb-automation"],
)

_FLAG_NAME = "stb_automation"


def _check_flag() -> None:
    """STB_AUTOMATION — Gate all endpoints behind feature flag."""
    if not feature_flags.is_enabled(_FLAG_NAME):
        raise HTTPException(
            status_code=404,
            detail="STB Automation is disabled. Enable the 'stb_automation' feature flag.",
        )


# ── Status ──────────────────────────────────────────────────────────


class StbStatus(BaseModel):
    logcat_monitor_active: bool = False
    logcat_session_id: Optional[str] = None
    logcat_serial: Optional[str] = None
    crawl: CrawlStatus = CrawlStatus()


@router.get("/status")
async def stb_status() -> StbStatus:
    """STB_AUTOMATION — Overall automation status."""
    _check_flag()
    monitor = get_monitor()
    return StbStatus(
        logcat_monitor_active=monitor.is_active,
        logcat_session_id=monitor.session_id,
        logcat_serial=monitor.serial,
    )


# ── Screen State ────────────────────────────────────────────────────


class ScreenStateResponse(BaseModel):
    state: ScreenState
    fingerprint: str


class StartMonitorRequest(BaseModel):
    serial: str
    tags: Optional[List[str]] = None


@router.get("/state")
async def get_state(
    serial: str = Query(..., description="ADB device serial"),
    include_hierarchy: bool = Query(True, description="Include uiautomator dump"),
) -> ScreenStateResponse:
    """STB_AUTOMATION — Read the current screen state via ADB.

    Returns the foreground activity, UI hierarchy, focused element,
    and a fingerprint suitable for navigation graph identity.
    """
    _check_flag()

    if settings.mock_mode:
        state = screen_reader.mock_screen_state()
    else:
        monitor = get_monitor()
        recent = monitor.get_events(last_n=5) if monitor.is_active else []
        state = await screen_reader.read_screen_state(
            serial=serial,
            recent_events=recent,
            include_hierarchy=include_hierarchy,
        )

    return ScreenStateResponse(
        state=state,
        fingerprint=fp.fingerprint(state),
    )


# ── Logcat Events ──────────────────────────────────────────────────


@router.get("/events")
async def get_events(
    last_n: int = Query(20, ge=1, le=50, description="Number of recent events"),
) -> List[LogcatEvent]:
    """STB_AUTOMATION — Recent logcat events (activity transitions, focus changes)."""
    _check_flag()
    monitor = get_monitor()
    return monitor.get_events(last_n=last_n)


# ── Monitor Control ─────────────────────────────────────────────────


@router.post("/monitor/start")
async def start_monitor(req: StartMonitorRequest) -> dict:
    """STB_AUTOMATION — Start the logcat monitor for a device."""
    _check_flag()
    monitor = get_monitor()
    if monitor.is_active:
        return {
            "status": "already_running",
            "session_id": monitor.session_id,
            "serial": monitor.serial,
        }

    session_id = await monitor.start(serial=req.serial, tags=req.tags)
    return {
        "status": "started",
        "session_id": session_id,
        "serial": req.serial,
    }


@router.post("/monitor/stop")
async def stop_monitor() -> dict:
    """STB_AUTOMATION — Stop the logcat monitor."""
    _check_flag()
    monitor = get_monitor()
    if not monitor.is_active:
        return {"status": "not_running"}

    await monitor.stop()
    return {"status": "stopped"}


# ── Navigation (Phase 1B) ──────────────────────────────────────────


class NavigateRequest(BaseModel):
    serial: str
    action: str  # keycode name: up, down, left, right, enter, back, home, ...
    settle_timeout_ms: int = 3000


class NavigateResponse(BaseModel):
    action: str
    pre_state: ScreenState
    post_state: ScreenState
    pre_fingerprint: str
    post_fingerprint: str
    transitioned: bool
    settle_method: str
    settle_ms: float


@router.post("/navigate")
async def navigate(req: NavigateRequest) -> NavigateResponse:
    """STB_AUTOMATION — Send a key press and observe the result.

    Sends the key via ADB, then uses tiered settle detection:
    logcat events (fastest) → dumpsys poll → uiautomator hash → timeout.
    Returns before/after screen state with timing metadata.
    """
    _check_flag()

    if settings.mock_mode:
        result = await action_executor.navigate_mock(req.action)
    else:
        result = await action_executor.navigate(
            serial=req.serial,
            action=req.action,
            settle_timeout_ms=req.settle_timeout_ms,
        )

    return NavigateResponse(
        action=result.action,
        pre_state=result.pre_state,
        post_state=result.post_state,
        pre_fingerprint=result.pre_fingerprint,
        post_fingerprint=result.post_fingerprint,
        transitioned=result.transitioned,
        settle_method=result.settle_method,
        settle_ms=round(result.settle_ms, 1),
    )
