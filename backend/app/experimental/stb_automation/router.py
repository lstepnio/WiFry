"""STB_AUTOMATION — FastAPI router for STB test automation.

Phase 1A endpoints:
  GET  /api/v1/experimental/stb/status  — Overall automation status
  GET  /api/v1/experimental/stb/state   — Current screen state via ADB
  GET  /api/v1/experimental/stb/events  — Recent logcat events

Phase 1B endpoints:
  POST /api/v1/experimental/stb/navigate — Send key + observe result

Phase 1D endpoints:
  GET  /api/v1/experimental/stb/anomalies           — List detected anomalies
  GET  /api/v1/experimental/stb/anomalies/patterns   — List anomaly patterns
  PUT  /api/v1/experimental/stb/anomalies/patterns   — Update anomaly patterns
  POST /api/v1/experimental/stb/diagnostics/collect   — Manual diagnostic trigger

All endpoints return 404 if the feature flag is disabled.
"""

import asyncio
import logging
import time
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ...config import settings
from ...services import feature_flags
from . import action_executor, chaos_engine, crawl_engine, diagnostics, fingerprint as fp, nav_model, nl_runner, screen_reader, test_flows, ui_map, vision_cache
from .anomaly_detector import get_detector
from .logcat_monitor import get_monitor
from .models import AnomalyPattern, ChaosConfig, ChaosResult, CrawlConfig, CrawlStatus, DetectedAnomaly, LogcatEvent, NavigationModel, ScreenNode, ScreenState, TestFlow, TestFlowRun, TestStep, VisionAnalysis

logger = logging.getLogger("wifry.stb_automation.router")

router = APIRouter(
    prefix="/api/v1/experimental/stb",
    tags=["stb-automation"],
)

_FLAG_NAME = "stb_automation"

# ── Vision cache — backed by vision_cache module ──────────────────
# All cache state (OrderedDict, nav counter, hit/miss stats) lives
# in vision_cache.py for clean persistence and future Redis swap.


class VisionDiag(BaseModel):
    """Diagnostics for vision cache behavior."""
    cache_hit: bool = False
    cache_key: str = ""  # perceptual hash of current frame
    cache_key_source: str = ""  # "perceptual" / "sha256" / "adb"
    cache_age_ms: int = 0  # how old the cached result is (0 if fresh)
    cache_size: int = 0  # total entries in cache
    api_call_ms: int = 0  # time for AI API call (0 if cache hit)
    error: Optional[str] = None
    streamer_running: bool = False
    # Perceptual hash diagnostics
    nav_sequence: int = 0  # current nav counter
    cached_nav_sequence: int = -1  # nav counter when last cache hit occurred
    hamming_distance: int = -1  # distance to matched cache entry (-1 = not computed)
    hamming_threshold: int = 0  # configured threshold
    hash_type: str = ""  # "perceptual" / "sha256" / "adb"
    invalidation_reason: str = ""  # "cache_hit" / "nav_fast_path" / "screen_changed" / "no_cache"
    # Hit ratio
    cache_hits_total: int = 0
    cache_misses_total: int = 0
    cache_hit_ratio_pct: float = 0.0


def _fill_ratio(diag: VisionDiag) -> None:
    """Populate hit ratio fields on diagnostics."""
    s = vision_cache.stats()
    diag.cache_hits_total = s["hits"]
    diag.cache_misses_total = s["misses"]
    diag.cache_hit_ratio_pct = s["hit_ratio_pct"]


def _check_vision_cache(
    threshold_override: Optional[int] = None,
) -> tuple[Optional[VisionAnalysis], VisionDiag, Optional[bytes], Optional[str]]:
    """Check the vision cache WITHOUT any ADB data.

    Returns
    -------
    (vision, diag, frame, cache_key)
        - On cache hit: vision is the cached result, frame/cache_key are set
        - On cache miss: vision is None, frame/cache_key are set for the
          caller to pass to ``_run_vision_analysis()``
    """
    threshold = threshold_override if threshold_override is not None else settings.stb_vision_cache_distance
    s = vision_cache.stats()

    diag = VisionDiag(
        cache_size=s["size"],
        nav_sequence=s["nav_sequence"],
        cached_nav_sequence=s["last_cache_hit_nav_seq"],
        hamming_threshold=threshold,
    )

    try:
        from ..video_capture import streamer
        diag.streamer_running = streamer.is_running()
    except ImportError:
        diag.streamer_running = False

    # ── Fast path: no navigation since last cache hit ──────────────
    fast_result = vision_cache.check_fast_path()
    if fast_result is not None:
        diag.cache_hit = True
        diag.invalidation_reason = "nav_fast_path"
        diag.hash_type = "fast_path"
        diag.cache_key = "(skipped)"
        diag.cache_key_source = "nav_counter"
        _fill_ratio(diag)
        return fast_result, diag, None, None

    # ── Get HDMI frame ─────────────────────────────────────────────
    frame: Optional[bytes] = None
    if diag.streamer_running:
        try:
            from ..video_capture import streamer
            frame = streamer.get_latest_frame()
        except ImportError:
            pass

    # ── Compute cache key ──────────────────────────────────────────
    cache_key: Optional[str] = None
    if frame:
        cache_key = fp.frame_hash(frame)
        if cache_key.startswith("sha256:"):
            diag.cache_key_source = "sha256_raw"
            diag.hash_type = "sha256_raw"
        else:
            diag.cache_key_source = "quantized"
            diag.hash_type = "quantized"
        diag.cache_key = cache_key

    # ── Cache lookup (exact match — quantized hash is deterministic) ──
    if cache_key:
        cached_result = vision_cache.get(cache_key)
        if cached_result is not None:
            diag.cache_hit = True
            diag.hamming_distance = 0
            diag.invalidation_reason = "cache_hit"
            diag.cache_size = s["size"]

            vision_cache.update_fast_path(cached_result)
            _fill_ratio(diag)
            return cached_result, diag, frame, cache_key

    # Not in cache — return miss for caller to handle
    diag.hamming_distance = 999
    _fill_ratio(diag)
    return None, diag, frame, cache_key


async def _run_vision_analysis(
    frame: Optional[bytes],
    cache_key: Optional[str],
    diag: VisionDiag,
    adb_visual_hash: str = "",
    system_prompt: Optional[str] = None,
) -> tuple[Optional[VisionAnalysis], VisionDiag]:
    """Run AI vision analysis on cache miss.

    Called after ``_check_vision_cache()`` returns None.  Handles the
    ADB fallback key, API call, and cache storage.
    """
    # Use ADB visual hash as fallback key when no frame available
    if not cache_key and adb_visual_hash:
        cache_key = adb_visual_hash
        diag.cache_key_source = "adb"
        diag.hash_type = "adb"
        diag.cache_key = cache_key

        # Check cache with ADB key
        cached_result = vision_cache.get(cache_key)
        if cached_result is not None:
            diag.cache_hit = True
            diag.hamming_distance = 0
            diag.invalidation_reason = "cache_hit"
            diag.cache_size = vision_cache.stats()["size"]
            vision_cache.update_fast_path(cached_result)
            _fill_ratio(diag)
            return cached_result, diag

    if not diag.streamer_running:
        diag.error = "HDMI streamer not running"
        diag.invalidation_reason = "no_streamer"
        _fill_ratio(diag)
        return None, diag

    if frame is None:
        diag.error = "No HDMI frame available"
        diag.invalidation_reason = "no_frame"
        _fill_ratio(diag)
        return None, diag

    s = vision_cache.stats()
    diag.invalidation_reason = "screen_changed" if s["size"] > 0 else "no_cache"

    try:
        from ..video_capture import analyzer

        t0 = time.time()
        result = await analyzer.analyze_frame(
            frame_jpeg=frame,
            system_prompt=system_prompt,
        )
        diag.api_call_ms = int((time.time() - t0) * 1000)

        vision_obj = VisionAnalysis(
            screen_type=result.screen_type or "unknown",
            screen_title=result.screen_title or "",
            focused_label=result.focused_element.label if result.focused_element else "",
            focused_position=result.focused_element.position if result.focused_element else "",
            focused_confidence=result.focused_element.confidence if result.focused_element else "low",
            navigation_path=result.navigation_path or [],
            visible_text=result.visible_text_summary or "",
            raw_description=result.raw_description or "",
            provider=result.provider or "",
            tokens_used=result.tokens_used or 0,
        )

        # Store in cache
        if cache_key:
            vision_cache.put(cache_key, vision_obj)

        diag.cache_size = vision_cache.stats()["size"]
        vision_cache.update_fast_path(vision_obj)

        _fill_ratio(diag)
        return vision_obj, diag

    except ImportError:
        diag.error = "Video capture module not available"
        _fill_ratio(diag)
        return None, diag
    except Exception as e:
        diag.error = str(e)
        logger.warning("Vision analysis failed: %s", e)
        _fill_ratio(diag)
        return None, diag


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


class UIMapDiag(BaseModel):
    """UI map diagnostics for the current state."""
    screen_key: str = ""
    last_action: str = ""
    from_focused: str = ""
    to_focused: str = ""  # what the map predicted or observed
    observation_recorded: bool = False
    observation_skipped_reason: str = ""  # why observation was skipped
    prediction_available: bool = False
    prediction_confidence: float = 0.0
    prediction_observations: int = 0
    map_entries_for_screen: int = 0  # total entries for this screen


class ScreenStateDiag(BaseModel):
    """Diagnostics attached to every /state response."""
    fingerprint: str = ""  # stable nav-graph identity
    visual_hash: str = ""  # volatile hash (changes with focus/text)
    fingerprint_inputs: str = ""  # what went into the fingerprint
    vision: Optional[VisionDiag] = None  # vision cache diagnostics
    ui_map: Optional[UIMapDiag] = None  # UI map diagnostics
    adb_signals: int = 0  # number of non-empty ADB signal fields
    read_ms: int = 0  # total time to read state (kept for backward compat)
    # Per-stage timing breakdown
    adb_foreground_ms: int = 0
    adb_hierarchy_ms: int = 0
    adb_fragments_ms: int = 0
    adb_window_title_ms: int = 0
    adb_total_ms: int = 0
    fingerprint_ms: int = 0
    frame_hash_ms: int = 0
    total_ms: int = 0
    vision_fast_path: bool = False  # True when cache hit skipped full ADB


class ScreenStateResponse(BaseModel):
    state: ScreenState
    fingerprint: str
    diag: Optional[ScreenStateDiag] = None


class StartMonitorRequest(BaseModel):
    serial: str
    tags: Optional[List[str]] = None


@router.get("/state")
async def get_state(
    serial: str = Query(..., description="ADB device serial"),
    include_hierarchy: bool = Query(True, description="Include uiautomator dump"),
    include_vision: bool = Query(False, description="Include AI vision analysis of HDMI frame"),
    vision_threshold: Optional[int] = Query(None, ge=0, le=50, description="Override Hamming distance threshold for vision cache (0=exact match only, default from config)"),
    vision_prompt: Optional[str] = Query(None, description="Override the default vision system prompt"),
) -> ScreenStateResponse:
    """STB_AUTOMATION — Read the current screen state via ADB + optional vision.

    Returns the foreground activity, UI hierarchy, focused element,
    and a fingerprint suitable for navigation graph identity.

    When ``include_vision=true``, the vision cache is checked **first**
    (before any ADB work).  On a cache hit, only minimal ADB data is
    collected (~50-100ms vs 400-800ms for full hierarchy).

    Always includes diagnostics showing cache hits, hash values, and timing.
    """
    _check_flag()

    t0 = time.time()
    timings = screen_reader.ReadTimings()

    if settings.mock_mode:
        state = screen_reader.mock_screen_state()
        stable_fp = fp.fingerprint(state)
        volatile_vh = fp.visual_hash(state)
        diag = ScreenStateDiag(
            fingerprint=stable_fp,
            visual_hash=volatile_vh,
            fingerprint_inputs=f"pkg={state.package} act={state.activity} elements={len(state.ui_elements)} frags={len(state.fragments)}",
            adb_signals=7,
        )
        diag.total_ms = int((time.time() - t0) * 1000)
        diag.read_ms = diag.total_ms
        return ScreenStateResponse(state=state, fingerprint=stable_fp, diag=diag)

    # ── Vision-first fast path ─────────────────────────────────────
    # When vision is requested, check the cache BEFORE any ADB work.
    # On a cache hit, skip the expensive hierarchy dump entirely.
    if include_vision:
        t_hash = time.time()
        vision, vision_diag, frame, cache_key = _check_vision_cache(
            threshold_override=vision_threshold,
        )
        frame_hash_ms = int((time.time() - t_hash) * 1000)

        if vision is not None:
            # ── CACHE HIT: minimal ADB only ───────────────────────
            monitor = get_monitor()
            recent = monitor.get_events(last_n=5) if monitor.is_active else []
            state, timings = await screen_reader.read_screen_state_minimal(
                serial=serial,
                recent_events=recent,
            )

            state.vision = vision
            _enrich_focused_context(state, vision)

            # Record observation in UI map — cache hits are as trustworthy
            # as fresh AI calls (same pixels = same result by definition)
            map_diag = UIMapDiag()
            if vision.focused_label:
                screen_key = f"{state.package}/{state.activity}"
                _map_action = ui_map.get_last_action()
                _map_from_focused = ui_map.get_last_focused(screen_key)
                map_diag.screen_key = screen_key
                map_diag.last_action = _map_action
                map_diag.from_focused = _map_from_focused
                map_diag.to_focused = vision.focused_label
                map_diag.map_entries_for_screen = len(ui_map.get_screen_entries(screen_key))
                if _map_action and _map_from_focused:
                    ui_map.observe(
                        screen_key=screen_key,
                        action=_map_action,
                        from_focused=_map_from_focused,
                        to_focused=vision.focused_label,
                        to_screen_type=vision.screen_type,
                        to_screen_title=vision.screen_title,
                        to_focused_position=vision.focused_position,
                        to_focused_confidence=vision.focused_confidence,
                        to_navigation_path=vision.navigation_path,
                    )
                    map_diag.observation_recorded = True
                else:
                    map_diag.observation_skipped_reason = (
                        "no_action" if not _map_action else "no_from_focused"
                    )
                ui_map.set_last_focused(screen_key, vision.focused_label)

            stable_fp = fp.fingerprint(state)
            diag = _build_diag(state, stable_fp, "", timings)
            diag.vision = vision_diag
            diag.ui_map = map_diag
            diag.frame_hash_ms = frame_hash_ms
            diag.vision_fast_path = True
            diag.total_ms = int((time.time() - t0) * 1000)
            diag.read_ms = diag.total_ms
            return ScreenStateResponse(state=state, fingerprint=stable_fp, diag=diag)

        # ── UI MAP PREDICTION (before expensive AI call) ──────────
        # If we know the screen, action, and previous focused element,
        # the UI map may predict the new state without any AI call.
        _map_screen_key = ""
        _map_from_focused = ""
        _map_action = ui_map.get_last_action()

        # Read minimal ADB to get screen_key for prediction
        monitor = get_monitor()
        recent = monitor.get_events(last_n=5) if monitor.is_active else []
        state, timings = await screen_reader.read_screen_state(
            serial=serial,
            recent_events=recent,
            include_hierarchy=False,
        )
        _map_screen_key = f"{state.package}/{state.activity}"
        _map_from_focused = ui_map.get_last_focused(_map_screen_key)

        # Attempt prediction
        map_prediction = ui_map.predict(
            screen_key=_map_screen_key,
            action=_map_action,
            from_focused=_map_from_focused,
        ) if _map_action and _map_from_focused else None

        # ── MAP HIT: use prediction, skip AI call entirely ────────
        if map_prediction is not None:
            vision_cache.credit_map_hit()  # correct hit/miss ratio
            predicted_vision = VisionAnalysis(
                screen_type=map_prediction.to_screen_type,
                screen_title=map_prediction.to_screen_title,
                focused_label=map_prediction.to_focused,
                focused_position=map_prediction.to_focused_position,
                focused_confidence=map_prediction.to_focused_confidence,
                navigation_path=map_prediction.to_navigation_path,
                provider="ui_map",
                tokens_used=0,
            )
            state.vision = predicted_vision
            _enrich_focused_context(state, predicted_vision)
            ui_map.set_last_focused(_map_screen_key, map_prediction.to_focused)

            # Record as observation (reinforces confidence)
            ui_map.observe(
                screen_key=_map_screen_key,
                action=_map_action,
                from_focused=_map_from_focused,
                to_focused=map_prediction.to_focused,
                to_screen_type=map_prediction.to_screen_type,
                to_screen_title=map_prediction.to_screen_title,
                to_focused_position=map_prediction.to_focused_position,
                to_focused_confidence=map_prediction.to_focused_confidence,
                to_navigation_path=map_prediction.to_navigation_path,
            )

            stable_fp = fp.fingerprint_from_activity(state.package, state.activity)
            diag = _build_diag(state, stable_fp, "", timings)
            diag.frame_hash_ms = frame_hash_ms
            diag.vision = vision_diag
            map_diag = UIMapDiag(
                screen_key=_map_screen_key,
                last_action=_map_action,
                from_focused=_map_from_focused,
                to_focused=map_prediction.to_focused,
                observation_recorded=True,
                prediction_available=True,
                prediction_confidence=map_prediction.confidence,
                prediction_observations=map_prediction.observation_count,
                map_entries_for_screen=len(ui_map.get_screen_entries(_map_screen_key)),
            )
            diag.ui_map = map_diag
            diag.total_ms = int((time.time() - t0) * 1000)
            diag.read_ms = diag.total_ms
            return ScreenStateResponse(state=state, fingerprint=stable_fp, diag=diag)

        # ── CACHE MISS + NO MAP: AI vision call ──────────────────
        vision_task = _run_vision_analysis(
            frame=frame,
            cache_key=cache_key,
            diag=vision_diag,
            system_prompt=vision_prompt,
        )
        vision, vision_diag = await vision_task

        stable_fp = fp.fingerprint_from_activity(state.package, state.activity)
        diag = _build_diag(state, stable_fp, "", timings)
        diag.frame_hash_ms = frame_hash_ms
        diag.vision = vision_diag

        map_diag = UIMapDiag(
            screen_key=_map_screen_key,
            last_action=_map_action,
            from_focused=_map_from_focused,
            map_entries_for_screen=len(ui_map.get_screen_entries(_map_screen_key)),
        )

        if vision:
            state.vision = vision
            _enrich_focused_context(state, vision)
            map_diag.to_focused = vision.focused_label

            # Record observation in UI map
            if _map_from_focused and _map_action and vision.focused_label:
                ui_map.observe(
                    screen_key=_map_screen_key,
                    action=_map_action,
                    from_focused=_map_from_focused,
                    to_focused=vision.focused_label,
                    to_screen_type=vision.screen_type,
                    to_screen_title=vision.screen_title,
                    to_focused_position=vision.focused_position,
                    to_focused_confidence=vision.focused_confidence,
                    to_navigation_path=vision.navigation_path,
                )
                map_diag.observation_recorded = True
            else:
                map_diag.observation_skipped_reason = (
                    "no_action" if not _map_action
                    else "no_from_focused" if not _map_from_focused
                    else "no_focused_label" if not vision.focused_label
                    else ""
                )

            # Update last focused for next prediction
            if vision.focused_label:
                ui_map.set_last_focused(_map_screen_key, vision.focused_label)

        diag.ui_map = map_diag
        diag.total_ms = int((time.time() - t0) * 1000)
        diag.read_ms = diag.total_ms
        return ScreenStateResponse(state=state, fingerprint=stable_fp, diag=diag)

    # ── No vision: standard ADB-only path (with parallelization) ──
    monitor = get_monitor()
    recent = monitor.get_events(last_n=5) if monitor.is_active else []
    state, timings = await screen_reader.read_screen_state(
        serial=serial,
        recent_events=recent,
        include_hierarchy=include_hierarchy,
    )

    stable_fp = fp.fingerprint(state)
    volatile_vh = fp.visual_hash(state)
    diag = _build_diag(state, stable_fp, volatile_vh, timings)
    diag.total_ms = int((time.time() - t0) * 1000)
    diag.read_ms = diag.total_ms
    return ScreenStateResponse(state=state, fingerprint=stable_fp, diag=diag)


def _build_diag(
    state: ScreenState,
    stable_fp: str,
    volatile_vh: str,
    timings: screen_reader.ReadTimings,
) -> ScreenStateDiag:
    """Build diagnostics with ADB signal count and timing breakdown."""
    adb_signals = sum([
        bool(state.package),
        bool(state.activity),
        bool(state.window_title),
        bool(state.focused_element),
        bool(state.focused_context),
        len(state.fragments) > 0,
        len(state.ui_elements) > 0,
    ])

    t_fp = time.time()
    # fingerprint already computed by caller — this just measures overhead
    fingerprint_ms = 0  # accounted for in caller
    _ = t_fp  # suppress unused

    return ScreenStateDiag(
        fingerprint=stable_fp,
        visual_hash=volatile_vh,
        fingerprint_inputs=f"pkg={state.package} act={state.activity} elements={len(state.ui_elements)} frags={len(state.fragments)}",
        adb_signals=adb_signals,
        adb_foreground_ms=timings.foreground_ms,
        adb_hierarchy_ms=timings.hierarchy_ms,
        adb_fragments_ms=timings.fragments_ms,
        adb_window_title_ms=timings.window_title_ms,
        adb_total_ms=timings.total_ms,
        fingerprint_ms=fingerprint_ms,
    )


def _enrich_focused_context(state: ScreenState, vision: VisionAnalysis) -> None:
    """Enrich focused_context with vision data when ADB signals are sparse."""
    if vision.focused_label:
        vision_ctx = f"vision: {vision.focused_label}"
        if vision.focused_position:
            vision_ctx += f" ({vision.focused_position})"
        if state.focused_context:
            state.focused_context = f"{vision_ctx} | {state.focused_context}"
        else:
            state.focused_context = vision_ctx


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
    timing: Optional[dict] = None


@router.post("/navigate")
async def navigate(req: NavigateRequest) -> NavigateResponse:
    """STB_AUTOMATION — Send a key press and observe the result.

    Sends the key via ADB, then uses tiered settle detection:
    logcat events (fastest) → dumpsys poll → uiautomator hash → timeout.
    Returns before/after screen state with timing metadata.
    """
    _check_flag()

    # Increment nav counter so vision cache fast-path knows to re-hash
    vision_cache.increment_nav()
    # Record last action for UI map predictions
    ui_map.set_last_action(req.action)

    if settings.mock_mode:
        result = await action_executor.navigate_mock(req.action)
    else:
        result = await action_executor.navigate(
            serial=req.serial,
            action=req.action,
            settle_timeout_ms=req.settle_timeout_ms,
        )

    # Record step if recording is active
    if test_flows.is_recording():
        test_flows.record_step(
            action=result.action,
            pre_fingerprint=result.pre_fingerprint,
            post_fingerprint=result.post_fingerprint,
            settle_ms=result.settle_ms,
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
        timing=result.timing,
    )


# ── Crawl (Phase 1C) ────────────────────────────────────────────────


@router.post("/crawl/start")
async def start_crawl(config: CrawlConfig) -> CrawlStatus:
    """STB_AUTOMATION — Start a BFS crawl of the STB UI."""
    _check_flag()
    return await crawl_engine.start_crawl(config)


@router.post("/crawl/stop")
async def stop_crawl() -> CrawlStatus:
    """STB_AUTOMATION — Stop the running crawl and persist the model."""
    _check_flag()
    return await crawl_engine.stop_crawl()


@router.post("/crawl/step")
async def crawl_step(config: CrawlConfig) -> dict:
    """STB_AUTOMATION — Execute a single manual exploration step."""
    _check_flag()
    return await crawl_engine.crawl_step(config)


# ── Navigation Model (Phase 1C) ────────────────────────────────────


@router.get("/model")
async def get_model(
    device_id: str = Query(..., description="Device serial / ID"),
) -> NavigationModel:
    """STB_AUTOMATION — Get the full navigation model for a device."""
    _check_flag()
    model = nav_model.get_model(device_id)
    if model is None:
        raise HTTPException(status_code=404, detail=f"No model found for device '{device_id}'")
    return model


@router.get("/model/{node_id}")
async def get_model_node(
    node_id: str,
    device_id: str = Query(..., description="Device serial / ID"),
) -> ScreenNode:
    """STB_AUTOMATION — Get a specific node from the navigation model."""
    _check_flag()
    model = nav_model.get_model(device_id)
    if model is None:
        raise HTTPException(status_code=404, detail=f"No model found for device '{device_id}'")
    node = nav_model.get_node(model, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")
    return node


class PathRequest(BaseModel):
    device_id: str
    from_node: str
    to_node: str


class PathResponse(BaseModel):
    found: bool
    actions: List[str]
    hop_count: int


@router.post("/model/path")
async def find_path(req: PathRequest) -> PathResponse:
    """STB_AUTOMATION — Find shortest action sequence between two nodes."""
    _check_flag()
    model = nav_model.get_model(req.device_id)
    if model is None:
        raise HTTPException(status_code=404, detail=f"No model found for device '{req.device_id}'")
    path = nav_model.find_path(model, req.from_node, req.to_node)
    if path is None:
        return PathResponse(found=False, actions=[], hop_count=0)
    return PathResponse(found=True, actions=path, hop_count=len(path))


@router.delete("/model")
async def delete_model(
    device_id: str = Query(..., description="Device serial / ID"),
) -> dict:
    """STB_AUTOMATION — Delete the navigation model for a device."""
    _check_flag()
    deleted = nav_model.delete_model(device_id)
    return {"deleted": deleted, "device_id": device_id}


# ── Anomaly Detection (Phase 1D) ───────────────────────────────────


# ── Vision Cache Debug ─────────────────────────────────────────────


class VisionCacheEntry(BaseModel):
    """Single entry from the vision cache for debug inspection."""
    hash_key: str
    screen_type: str = ""
    screen_title: str = ""
    focused_label: str = ""
    tokens_used: int = 0


class VisionCacheDebug(BaseModel):
    """Full vision cache state for debugging."""
    size: int = 0
    max_size: int = 0
    threshold: int = 0
    nav_sequence: int = 0
    has_perceptual_hash: bool = False
    hits_total: int = 0
    misses_total: int = 0
    hit_ratio_pct: float = 0.0
    entries: List[VisionCacheEntry] = []


@router.get("/vision/prompt")
async def get_vision_prompt() -> dict:
    """STB_AUTOMATION — Get the default vision prompts for editing."""
    _check_flag()
    from ..video_capture import analyzer
    sys_prompt, usr_prompt = analyzer.get_default_prompts()
    return {"system_prompt": sys_prompt, "user_prompt": usr_prompt}


@router.get("/vision/cache")
async def get_vision_cache_debug() -> VisionCacheDebug:
    """STB_AUTOMATION — Dump the vision cache for debugging."""
    _check_flag()
    entries = []
    for key, analysis in vision_cache.items():
        entries.append(VisionCacheEntry(
            hash_key=key,
            screen_type=analysis.screen_type,
            screen_title=analysis.screen_title,
            focused_label=analysis.focused_label,
            tokens_used=analysis.tokens_used,
        ))
    s = vision_cache.stats()
    return VisionCacheDebug(
        size=s["size"],
        max_size=s["max_size"],
        threshold=settings.stb_vision_cache_distance,
        nav_sequence=s["nav_sequence"],
        has_perceptual_hash=fp.has_perceptual_hash(),
        hits_total=s["hits"],
        misses_total=s["misses"],
        hit_ratio_pct=s["hit_ratio_pct"],
        entries=entries,
    )


@router.delete("/vision/cache")
async def clear_vision_cache_endpoint() -> dict:
    """STB_AUTOMATION — Clear the vision cache."""
    _check_flag()
    count = vision_cache.clear()
    return {"cleared": count}


# ── UI Map (learned menu patterns) ─────────────────────────────────


@router.get("/ui-map")
async def get_ui_map() -> dict:
    """STB_AUTOMATION — Get the learned UI map."""
    _check_flag()
    return {
        "screens": ui_map.get_all_screens(),
        "stats": ui_map.stats(),
    }


@router.get("/ui-map/screen")
async def get_ui_map_screen(screen_key: str = Query(...)) -> dict:
    """STB_AUTOMATION — Get all learned transitions for a screen."""
    _check_flag()
    entries = ui_map.get_screen_entries(screen_key)
    return {
        "screen_key": screen_key,
        "entries": [e.model_dump() for e in entries],
    }


@router.get("/ui-map/graph")
async def get_ui_map_graph() -> dict:
    """STB_AUTOMATION — Get the full UI map as a graph (nodes + edges)."""
    _check_flag()
    all_screens = ui_map.get_all_screens()
    nodes = []  # unique focused elements across all screens
    edges = []  # transitions
    node_set: set = set()

    for screen_summary in all_screens:
        screen_key = screen_summary["screen_key"]
        entries = ui_map.get_screen_entries(screen_key)
        for entry in entries:
            # Create node IDs that include screen context
            from_id = f"{screen_key}::{entry.from_focused}"
            to_id = f"{screen_key}::{entry.to_focused}"
            if from_id not in node_set:
                node_set.add(from_id)
                nodes.append({
                    "id": from_id,
                    "label": entry.from_focused,
                    "screen_key": screen_key,
                })
            if to_id not in node_set:
                node_set.add(to_id)
                nodes.append({
                    "id": to_id,
                    "label": entry.to_focused,
                    "screen_key": screen_key,
                    "screen_type": entry.to_screen_type,
                })
            edges.append({
                "from": from_id,
                "to": to_id,
                "action": entry.action,
                "confidence": entry.confidence,
                "observations": entry.observation_count,
                "screen_key": screen_key,
            })

    return {
        "nodes": nodes,
        "edges": edges,
        "screens": [s["screen_key"] for s in all_screens],
        "stats": ui_map.stats(),
    }


@router.get("/ui-map/stats")
async def get_ui_map_stats() -> dict:
    """STB_AUTOMATION — Get UI map prediction statistics."""
    _check_flag()
    return ui_map.stats()


@router.delete("/ui-map")
async def clear_ui_map() -> dict:
    """STB_AUTOMATION — Clear the learned UI map."""
    _check_flag()
    count = ui_map.clear()
    return {"cleared": count}


# ── Anomaly Detection (Phase 1D) ───────────────────────────────────


@router.get("/anomalies")
async def get_anomalies(
    last_n: int = Query(50, ge=1, le=200, description="Number of recent anomalies"),
) -> List[DetectedAnomaly]:
    """STB_AUTOMATION — List detected anomalies."""
    _check_flag()
    detector = get_detector()
    return detector.get_anomalies(last_n=last_n)


@router.get("/anomalies/patterns")
async def get_anomaly_patterns() -> List[AnomalyPattern]:
    """STB_AUTOMATION — List configured anomaly detection patterns."""
    _check_flag()
    detector = get_detector()
    return detector.patterns


@router.put("/anomalies/patterns")
async def set_anomaly_patterns(patterns: List[AnomalyPattern]) -> List[AnomalyPattern]:
    """STB_AUTOMATION — Update anomaly detection patterns."""
    _check_flag()
    detector = get_detector()
    detector.set_patterns(patterns)
    return detector.patterns


# ── Diagnostics (Phase 1D) ─────────────────────────────────────────


class DiagnosticsRequest(BaseModel):
    serial: str
    reason: str = "manual"
    severity: str = "medium"


@router.post("/diagnostics/collect")
async def collect_diagnostics(req: DiagnosticsRequest) -> dict:
    """STB_AUTOMATION — Manually trigger diagnostic collection.

    Collects screenshot, dumpsys outputs, and optionally bugreport
    from the STB.  All artifacts are linked to the active test session.
    """
    _check_flag()
    return await diagnostics.collect_diagnostics(
        serial=req.serial,
        reason=req.reason,
        severity=req.severity,
    )


# ── Test Flows (Phase 1E) ──────────────────────────────────────────


@router.get("/flows")
async def list_flows() -> List[TestFlow]:
    """STB_AUTOMATION — List all test flows."""
    _check_flag()
    return test_flows.list_flows()


@router.get("/flows/{flow_id}")
async def get_flow(flow_id: str) -> TestFlow:
    """STB_AUTOMATION — Get a test flow by ID."""
    _check_flag()
    flow = test_flows.get_flow(flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail=f"Flow '{flow_id}' not found")
    return flow


class CreateFlowRequest(BaseModel):
    name: str
    serial: str
    description: str = ""
    steps: Optional[List[TestStep]] = None
    source: str = "manual"


@router.post("/flows")
async def create_flow(req: CreateFlowRequest) -> TestFlow:
    """STB_AUTOMATION — Create a new test flow."""
    _check_flag()
    return test_flows.create_flow(
        name=req.name,
        serial=req.serial,
        description=req.description,
        steps=req.steps,
        source=req.source,
    )


class UpdateFlowRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    serial: Optional[str] = None
    steps: Optional[List[TestStep]] = None


@router.put("/flows/{flow_id}")
async def update_flow(flow_id: str, req: UpdateFlowRequest) -> TestFlow:
    """STB_AUTOMATION — Update a test flow (edit steps, rename, etc.)."""
    _check_flag()
    updates = req.model_dump(exclude_none=True)
    flow = test_flows.update_flow(flow_id, updates)
    if flow is None:
        raise HTTPException(status_code=404, detail=f"Flow '{flow_id}' not found")
    return flow


@router.delete("/flows/{flow_id}")
async def delete_flow(flow_id: str) -> dict:
    """STB_AUTOMATION — Delete a test flow."""
    _check_flag()
    deleted = test_flows.delete_flow(flow_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Flow '{flow_id}' not found")
    return {"deleted": True, "flow_id": flow_id}


@router.post("/flows/{flow_id}/run")
async def run_flow(flow_id: str) -> TestFlowRun:
    """STB_AUTOMATION — Execute a test flow.

    Replays steps sequentially with assertion checking and anomaly
    monitoring.  Runs as a background task.
    """
    _check_flag()
    try:
        return await test_flows.run_flow(flow_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/flows/{flow_id}/stop")
async def stop_flow(flow_id: str) -> dict:
    """STB_AUTOMATION — Stop a running test flow."""
    _check_flag()
    run = await test_flows.stop_flow()
    if run is None:
        return {"status": "not_running"}
    return {"status": "stopped", "run": run.model_dump()}


@router.get("/flows/{flow_id}/results")
async def get_flow_results(flow_id: str) -> dict:
    """STB_AUTOMATION — Get results of the last flow run."""
    _check_flag()
    run = test_flows.get_run_status()
    if run is None or run.flow_id != flow_id:
        raise HTTPException(status_code=404, detail="No run results for this flow")
    return run.model_dump()


# ── Recording Control (Phase 1E) ───────────────────────────────────


class StartRecordingRequest(BaseModel):
    name: str
    serial: str
    description: str = ""


@router.post("/flows/record/start")
async def start_recording(req: StartRecordingRequest) -> TestFlow:
    """STB_AUTOMATION — Start recording navigation steps into a new flow.

    After starting, all /navigate calls will be recorded as steps.
    """
    _check_flag()
    return test_flows.start_recording(
        name=req.name,
        serial=req.serial,
        description=req.description,
    )


@router.post("/flows/record/stop")
async def stop_recording() -> dict:
    """STB_AUTOMATION — Stop recording and finalize the flow."""
    _check_flag()
    flow = test_flows.stop_recording()
    if flow is None:
        return {"status": "not_recording"}
    return {"status": "stopped", "flow": flow.model_dump()}


# ── Chaos Mode (Phase 1F) ──────────────────────────────────────────


@router.post("/chaos/start")
async def start_chaos(config: ChaosConfig) -> ChaosResult:
    """STB_AUTOMATION — Start autonomous chaos exploration.

    Sends weighted-random key presses while monitoring for anomalies.
    Configurable duration, seed, key weights, and anomaly response.
    """
    _check_flag()
    return await chaos_engine.start_chaos(config)


@router.post("/chaos/stop")
async def stop_chaos() -> dict:
    """STB_AUTOMATION — Stop the running chaos session."""
    _check_flag()
    result = await chaos_engine.stop_chaos()
    if result is None:
        return {"status": "not_running"}
    return result.model_dump()


@router.get("/chaos/status")
async def chaos_status() -> dict:
    """STB_AUTOMATION — Current chaos run status + anomalies."""
    _check_flag()
    result = chaos_engine.get_status()
    if result is None:
        return {"state": "idle"}
    return result.model_dump()


# ── Natural Language Testing (Phase 1G) ───────────────────────────────


class NLGenerateRequest(BaseModel):
    prompt: str
    serial: str
    device_id: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None


@router.post("/nl/generate")
async def nl_generate(req: NLGenerateRequest) -> TestFlow:
    """STB_AUTOMATION — Generate a test flow from natural language.

    Translates a plain-English test description into an executable
    TestFlow with keyed navigation steps, waits, and assertions.
    Uses the navigation model (if available) for realistic paths.
    """
    _check_flag()
    try:
        return await nl_runner.generate_flow(
            prompt=req.prompt,
            serial=req.serial,
            device_id=req.device_id,
            provider=req.provider,
            model=req.model,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("[STB_AUTOMATION] NL generate failed")
        raise HTTPException(status_code=500, detail=f"NL generation failed: {e}")


class NLRefineRequest(BaseModel):
    refinement: str
    provider: Optional[str] = None
    model: Optional[str] = None


@router.post("/nl/refine/{flow_id}")
async def nl_refine(flow_id: str, req: NLRefineRequest) -> TestFlow:
    """STB_AUTOMATION — Refine an existing flow with a follow-up prompt.

    Sends the current flow + refinement instruction to the AI,
    which returns an updated version of the flow.
    """
    _check_flag()
    try:
        return await nl_runner.refine_flow(
            flow_id=flow_id,
            refinement_prompt=req.refinement,
            provider=req.provider,
            model=req.model,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("[STB_AUTOMATION] NL refine failed")
        raise HTTPException(status_code=500, detail=f"NL refinement failed: {e}")


# ── Vision Enrichment (Phase 1G) ─────────────────────────────────────


@router.post("/state/enrich")
async def enrich_state(
    serial: str = Query(..., description="ADB device serial"),
) -> dict:
    """STB_AUTOMATION — Add vision analysis to the current screen state.

    Captures an HDMI frame and runs AI vision analysis to identify
    screen type, focused element, navigation path, and visible text.
    Complements ADB-based state reading for ambiguous screens.
    """
    _check_flag()
    return await nl_runner.enrich_state_with_vision(serial)
