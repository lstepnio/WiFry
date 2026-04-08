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

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ...config import settings
from ...services import feature_flags
from . import action_executor, chaos_engine, crawl_engine, diagnostics, fingerprint as fp, nav_model, nl_runner, screen_reader, test_flows
from .anomaly_detector import get_detector
from .logcat_monitor import get_monitor
from .models import AnomalyPattern, ChaosConfig, ChaosResult, CrawlConfig, CrawlStatus, DetectedAnomaly, LogcatEvent, NavigationModel, ScreenNode, ScreenState, TestFlow, TestFlowRun, TestStep

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
